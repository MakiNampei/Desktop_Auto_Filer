import os
import sys
import time
import csv
import shutil
import logging
import requests
from pathlib import Path
from queue import Queue, Empty
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime

# Non-blocking key polling (Windows)
try:
    import msvcrt
except Exception:
    msvcrt = None

# ---------- logging ----------
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "DeskPilot")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "controller.log")
MOVES_CSV = os.path.join(LOG_DIR, "moves.csv")  # full move history

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_console)
info = logging.info; warn = logging.warning; err = logging.error

# ---------- config ----------
AGENT = os.environ.get("DESKPILOT_AGENT_URL", "http://localhost:8000")
USER_DESKTOP = Path(os.environ["USERPROFILE"]) / "Desktop"
UNDO_LOG = Path(__file__).with_name("undo_log.csv")

# ---------- fs helpers ----------
def ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

def safe_move(src: Path, dst_dir: Path) -> Path:
    ensure_dir(dst_dir)
    base, ext = src.stem, src.suffix
    candidate = dst_dir / (base + ext)
    n = 2
    while candidate.exists():
        candidate = dst_dir / f"{base} ({n}){ext}"
        n += 1
    shutil.move(str(src), str(candidate))
    return candidate

# ---------- move history (CSV) ----------
def _moves_csv_header_if_needed():
    if not os.path.exists(MOVES_CSV):
        with open(MOVES_CSV, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "action", "file_name",
                "src_path", "dst_path",
                "suggestion_id", "suggested_folder",
                "accepted", "confidence", "rationale", "note"
            ])

def log_move(action: str, src: Path | None, dst: Path | None,
             sug: dict | None, accepted: bool | None, note: str = ""):
    _moves_csv_header_if_needed()
    ts = datetime.now().isoformat(timespec="seconds")
    file_name = (src.name if isinstance(src, Path) else (dst.name if isinstance(dst, Path) else ""))
    suggestion_id = sug.get("suggestion_id") if sug else ""
    suggested_folder = sug.get("folder") if sug else ""
    confidence = f"{sug.get('confidence', ''):.2f}" if (sug and isinstance(sug.get("confidence", None), (int, float))) else ""
    rationale = (sug.get("rationale", "") if sug else "")
    if isinstance(rationale, str) and len(rationale) > 400:
        rationale = rationale[:400] + "…"
    with open(MOVES_CSV, "a", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerow([
            ts, action, file_name,
            str(src) if src else "", str(dst) if dst else "",
            suggestion_id, suggested_folder,
            "" if accepted is None else ("1" if accepted else "0"),
            confidence, rationale, note
        ])

def open_move_log():
    _moves_csv_header_if_needed()
    try:
        os.startfile(MOVES_CSV)  # default app (Excel/Notepad)
        info(f"[log] opened: {MOVES_CSV}")
    except Exception as e:
        err(f"[log] cannot open: {e}\nPath: {MOVES_CSV}")

# ---------- undo log ----------
def append_undo(src_before: Path, dst_after: Path):
    new = not UNDO_LOG.exists()
    with UNDO_LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["src_before", "dst_after"])
        w.writerow([str(src_before), str(dst_after)])

def undo_last():
    if not UNDO_LOG.exists():
        info("[undo] nothing to undo"); return None
    with UNDO_LOG.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        info("[undo] nothing to undo"); return None
    header, *recs = rows
    src_before, dst_after = recs[-1]
    dst_after_p = Path(dst_after)
    target_dir  = Path(src_before).parent
    restored = None
    if dst_after_p.exists():
        restored = safe_move(dst_after_p, target_dir)
        info(f"[undo] restored -> {restored}")
    with UNDO_LOG.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([header] + recs[:-1])
    return {"src_before": Path(src_before), "dst_after": Path(dst_after), "restored": restored}

# ---------- agent calls ----------
def health_ok() -> bool:
    try:
        r = requests.get(f"{AGENT}/health", timeout=2)
        return r.ok and r.json().get("status") == "up"
    except Exception:
        return False

def wait_for_agent(tag="startup"):
    info(f"[{tag}] waiting for agent at {AGENT} (retrying)...")
    tries = 0
    while True:
        if health_ok():
            info(f"[{tag}] agent is up.")
            return
        time.sleep(1); tries += 1
        if tries % 10 == 0: info(f"[{tag}] still waiting ({tries}s)...")

def ask_agent(path: Path):
    body = {"path": str(path), "name": path.name, "ext": path.suffix.lower()}
    r = requests.post(f"{AGENT}/suggest", json=body, timeout=20)
    r.raise_for_status()
    return r.json()

def send_feedback(suggestion_id: str, accepted: bool, chosen: Path | None = None):
    body = {"suggestion_id": suggestion_id, "accepted": accepted}
    if not accepted and chosen is not None:
        body["chosen_folder"] = str(chosen)
    r = requests.post(f"{AGENT}/feedback", json=body, timeout=5)
    r.raise_for_status()
    return r.json()

def get_whitelist():
    r = requests.get(f"{AGENT}/whitelist", timeout=5)
    r.raise_for_status()
    return r.json()["items"]

def add_to_whitelist(path: Path, description: str):
    body = {"path": str(path), "description": description}
    r = requests.post(f"{AGENT}/whitelist/add", json=body, timeout=5)
    r.raise_for_status()
    return r.json()

def remove_from_whitelist(path: Path):
    r = requests.post(f"{AGENT}/whitelist/remove", json={"path": str(path)}, timeout=5)
    r.raise_for_status()
    return r.json()

def clear_whitelist():
    r = requests.post(f"{AGENT}/whitelist/clear", json={}, timeout=5)
    r.raise_for_status()
    return r.json()

def reindex_whitelist():
    r = requests.post(f"{AGENT}/whitelist/reindex", json={}, timeout=10)
    r.raise_for_status()
    return r.json()

# ---------- whitelist UX ----------
def whitelist_setup_interactive():
    info("\n=== Whitelist setup ===")
    info("Enter folders to ALLOW moves into. Leave blank to finish.")
    while True:
        p = input("Folder path (blank to finish): ").strip().strip('"')
        if not p: break
        P = Path(os.path.expandvars(os.path.expanduser(p)))
        if not P.exists() or not P.is_dir():
            info("  ! Not a folder. Try again."); continue
        desc = input("  Short description (e.g., 'Invoices', 'Class EECS'): ").strip() or P.name
        try:
            add_to_whitelist(P, desc)
            info(f"  + Added: {P} ({desc})")
        except Exception as e:
            err(f"  ! Failed to add: {e}")
    info("Whitelist complete.\n")

def manage_whitelist_menu():
    while True:
        items = get_whitelist()
        info("\n=== Manage Whitelist ===")
        if not items:
            info("  (empty)")
        else:
            for i, it in enumerate(items, 1):
                info(f"  {i}. {it.get('description','(no desc)')}  —  {it['path']}")
        info("[A]dd  [D]elete one  [C]lear all  [R]eindex  [B]ack")
        cmd = input(">> ").strip().lower()
        if cmd == "a":
            whitelist_setup_interactive()
        elif cmd == "d":
            if not items:
                info("Nothing to delete.")
                continue
            sel = input("Number to delete: ").strip()
            try:
                idx = int(sel)
                if 1 <= idx <= len(items):
                    target = Path(os.path.expandvars(items[idx-1]["path"]))
                    remove_from_whitelist(target)
                    info("Removed; related memory purged on agent.")
                else:
                    info("Invalid number.")
            except ValueError:
                info("Cancelled.")
        elif cmd == "c":
            if input("Type 'YES' to clear ALL: ").strip() == "YES":
                clear_whitelist(); info("Whitelist cleared; memory purged.")
            else:
                info("Cancelled.")
        elif cmd == "r":
            reindex_whitelist(); info("Reindexed (if embeddings enabled).")
        elif cmd == "b":
            info("Returning to idle…")
            return
        else:
            info("...")

# ---------- watcher ----------
class Handler(FileSystemEventHandler):
    def __init__(self, q: Queue): super().__init__(); self.q = q
    def on_created(self, event):
        if event.is_directory: return
        p = Path(event.src_path)
        last = -1
        for _ in range(20):
            try: size = p.stat().st_size
            except FileNotFoundError: return
            if size == last: break
            last = size; time.sleep(0.2)
        if p.suffix.lower() in {".tmp", ".crdownload"} or p.name.startswith("~$"): return
        self.q.put(p); info(f"[watch] queued {p.name}")

def suggest_dialog(path: Path):
    while True:
        try:
            sug = ask_agent(path)
        except Exception as e:
            warn(f"[suggest error] {e}; waiting then retrying...")
            wait_for_agent("suggest")
            try:
                sug = ask_agent(path)
            except Exception as e2:
                err(f"[suggest retry failed] {e2}; skipping {path.name}")
                log_move("error", path, None, None, None, note=f"suggest failed: {e2}")
                return

        if sug.get("needs_whitelist"):
            info("Agent reports no whitelist configured. Running setup.")
            whitelist_setup_interactive()
            continue

        info("\n--- New file ---")
        info(f"File       : {path.name}")
        info(f"Suggest    : {sug['folder']}")
        info(f"Confidence : {sug['confidence']:.2f}")
        info(f"Because    : {sug['rationale']}")
        # Whitelist management removed from here
        info("[A]ccept  [C]hoose from whitelist  [S]kip  [U]ndo last  [Q]uit")
        cmd = input(">> ").strip().lower()

        if cmd == "a":
            try:
                newp = safe_move(path, Path(sug["folder"]))
                append_undo(path, newp)
                send_feedback(sug["suggestion_id"], True)
                info(f"✅ moved -> {newp}")
                log_move("accept", path, newp, sug, True)
            except Exception as e:
                err(f"[move error] {e}")
                log_move("accept_error", path, None, sug, True, note=str(e))
            return

        elif cmd == "c":
            items = get_whitelist()
            if not items:
                info("[wl] No whitelist yet. Use idle menu (W) to add folders.")
                continue
            info("\nSelect a destination (whitelist):")
            for i, it in enumerate(items, 1):
                info(f"  {i}. {it.get('description','(no desc)')}  —  {it['path']}")
            sel = input("Enter number (blank to cancel): ").strip()
            if not sel:
                info("skipped")
                log_move("choose_cancel", path, None, sug, None)
            else:
                try:
                    idx = int(sel)
                    if 1 <= idx <= len(items):
                        destP = Path(os.path.expandvars(items[idx-1]["path"]))
                        newp = safe_move(path, destP)
                        append_undo(path, newp)
                        send_feedback(sug["suggestion_id"], False, destP)
                        info(f"✅ moved -> {newp}")
                        log_move("choose", path, newp, sug, False)
                        return
                    else:
                        info("Invalid number.")
                except Exception as e:
                    err(f"[move error] {e}")
                    log_move("choose_error", path, None, sug, False, note=str(e))

        elif cmd == "u":
            details = undo_last()
            if details:
                log_move(
                    "undo",
                    details["dst_after"],
                    details["restored"],
                    None, None,
                    note=f"back to {details['src_before']}"
                )

        elif cmd == "s":
            info("skipped")
            log_move("skip", path, None, sug, None)
            return

        elif cmd == "q":
            info("bye")
            raise KeyboardInterrupt
        else:
            info("...")

# ---------- idle hotkeys ----------
def print_idle_menu_hint():
    info("\n[Menu] W = Manage whitelist   |   L = Open move log   |   Q = Quit")

def handle_idle_keys():
    if not msvcrt:
        return
    if msvcrt.kbhit():
        ch = msvcrt.getwch()
        if not ch:
            return
        ch = ch.lower()
        if ch == "w":
            manage_whitelist_menu()
            print_idle_menu_hint()
        elif ch == "l":
            open_move_log()
            print_idle_menu_hint()
        elif ch == "q":
            info("bye")
            raise KeyboardInterrupt

# ---------- main ----------
def main():
    info("=== DeskPilot Controller ===")
    info(f"Python: {sys.version.split()[0]}  |  Agent: {AGENT}")
    info(f"Watching: {USER_DESKTOP}")
    if not USER_DESKTOP.exists():
        try: USER_DESKTOP.mkdir(parents=True, exist_ok=True)
        except Exception as e: err(f"[startup] cannot create Desktop path: {e}"); input("Enter to exit..."); return

    wait_for_agent()
    wl = get_whitelist()
    info(f"[startup] whitelist has {len(wl)} folder(s).")
    if not wl:
        info("No whitelist found. Let's create one.")
        whitelist_setup_interactive()
        wl = get_whitelist()
        info(f"[startup] whitelist updated: {len(wl)} folder(s).")
        if not wl:
            info("No whitelist configured; staying idle. Press W to add, Q to quit.")

    q = Queue(); obs = Observer()
    try: obs.schedule(Handler(q), str(USER_DESKTOP), recursive=False); obs.start()
    except Exception as e: err(f"[watcher] failed to start observer: {e}"); input("Enter to exit..."); return

    print_idle_menu_hint()
    last_hint = time.time()

    try:
        while True:
            if time.time() - last_hint > 60:
                print_idle_menu_hint(); last_hint = time.time()

            try:
                handle_idle_keys()
            except KeyboardInterrupt:
                break

            try:
                path = q.get(timeout=0.2)
            except Empty:
                continue

            suggest_dialog(path)
            print_idle_menu_hint()
            last_hint = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        obs.stop(); obs.join()

if __name__ == "__main__":
    try: main()
    except Exception as e:
        err(f"[boot] unhandled: {e}")
        import traceback; traceback.print_exc()
        input("Press Enter to exit...")

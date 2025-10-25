import os, re, sys, json, time, shutil, csv
from dataclasses import dataclass
from typing import Optional, List, Dict

CONFIG_FILE = "rules.json"
UNDO_LOG    = "undo_log.csv"   # record the moves, so it is easy to undo later
SEEN_DB     = ".seen_files.txt" # keep a record of all the files that have already been detected and processed on the Desktop

@dataclass
class MoveRecord:
    src_before: str
    dst_after: str

def expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))

def load_config() -> Dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # list the base_dirs
    base = {k: expand(v) for k, v in cfg.get("base_dirs", {}).items()}
    cfg["base_dirs"] = base
    return cfg

def list_desktop_files(desktop_dir: str) -> List[str]:
    try:
        entries = [os.path.join(desktop_dir, x) for x in os.listdir(desktop_dir)]
        files = [p for p in entries if os.path.isfile(p)]
        # ignore the temp folder and hidden folder
        files = [p for p in files if not os.path.basename(p).startswith(".")]
        return files
    except FileNotFoundError:
        print(f"[!] Desktop not found: {desktop_dir}")
        return []

def tokenize_name(path: str) -> List[str]:
    name = os.path.splitext(os.path.basename(path))[0].lower()
    tokens = re.split(r"[^a-z0-9]+", name)
    return [t for t in tokens if len(t) >= 3]

def decide_destination(path: str, cfg: Dict) -> Optional[str]:
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    ext = ext[1:].lower()  # drop dot
    rules = cfg.get("rules", [])
    bases = cfg.get("base_dirs", {})
    # 1) extension
    for r in rules:
        exts = r.get("if_ext_in")
        if exts and ext in [e.lower() for e in exts]:
            return bases.get(r["to"])
    # 2) keywords
    lower = name.lower()
    for r in rules:
        kws = r.get("if_name_has_any")
        if kws and any(kw.lower() in lower for kw in kws):
            return bases.get(r["to"])
    # 3) regex
    for r in rules:
        regs = r.get("if_name_matches_any_regex")
        if regs and any(re.match(rx, name) for rx in regs):
            return bases.get(r["to"])
    # 4) others
    return bases.get(cfg.get("fallback_dir"))

def ensure_dir(p: str):
    if p and not os.path.isdir(p):
        os.makedirs(p, exist_ok=True)

def safe_move(src: str, dst_dir: str) -> str:
    #prevent name conflict
    ensure_dir(dst_dir)
    base = os.path.basename(src)
    name, ext = os.path.splitext(base)
    candidate = os.path.join(dst_dir, base)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(dst_dir, f"{name} ({n}){ext}")
        n += 1
    shutil.move(src, candidate)
    return candidate

def append_undo(rec: MoveRecord):
    new_file = not os.path.exists(UNDO_LOG)
    with open(UNDO_LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["src_before", "dst_after"])
        w.writerow([rec.src_before, rec.dst_after])

def undo_once():
    if not os.path.exists(UNDO_LOG):
        print("[i] nothing to undo")
        return
    with open(UNDO_LOG, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        print("[i] nothing to undo")
        return
    header, *recs = rows
    last = recs.pop()
    src_before, dst_after = last
    # move back to desktop
    target_dir = os.path.dirname(src_before)
    if not os.path.exists(dst_after):
        print(f"[!] missing moved file: {dst_after}")
    else:
        restored = safe_move(dst_after, target_dir)
        print(f"[undo] restored to {restored}")
    # write in logs
    with open(UNDO_LOG, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(recs)

def load_seen() -> set:
    s = set()
    if os.path.exists(SEEN_DB):
        with open(SEEN_DB, "r", encoding="utf-8") as f:
            for line in f:
                s.add(line.strip())
    return s

def save_seen(s: set):
    with open(SEEN_DB, "w", encoding="utf-8") as f:
        for p in sorted(s):
            f.write(p + "\n")

def organize_once(dry_run=False):
    cfg = load_config()
    desktop = cfg["base_dirs"]["desktop"]
    files = list_desktop_files(desktop)
    moved = 0
    for f in files:
        dest = decide_destination(f, cfg)
        if not dest or dest == os.path.dirname(f):
            continue
        if dry_run:
            print(f"[dry-run] {os.path.basename(f)} -> {dest}")
        else:
            newpath = safe_move(f, dest)
            append_undo(MoveRecord(src_before=f, dst_after=newpath))
            print(f"[move] {os.path.basename(f)} -> {dest}")
            moved += 1
    print(f"[done] moved: {moved}")

def watch_polling(interval_sec=2, dry_run=False):
    """watch"""
    cfg = load_config()
    desktop = cfg["base_dirs"]["desktop"]
    seen = load_seen()
    print(f"[watch] polling {desktop} every {interval_sec}s (dry_run={dry_run})")
    try:
        while True:
            files = list_desktop_files(desktop)
            for f in files:
                if f in seen:
                    continue
                seen.add(f)
                dest = decide_destination(f, cfg)
                if not dest or dest == os.path.dirname(f):
                    print(f"[skip] {os.path.basename(f)} (no-op)")
                    continue
                if dry_run:
                    print(f"[dry-run] {os.path.basename(f)} -> {dest}")
                else:
                    time.sleep(0.2)
                    if os.path.exists(f):
                        newpath = safe_move(f, dest)
                        append_undo(MoveRecord(src_before=f, dst_after=newpath))
                        print(f"[move] {os.path.basename(f)} -> {dest}")
            save_seen(seen)
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[watch] stopped.")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Desk file organizer (no deps)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--interval", type=int, default=2)
    args = ap.parse_args()

    if args.undo:
        undo_once()
        sys.exit(0)

    if args.once:
        organize_once(dry_run=args.dry_run); sys.exit(0)

    if args.watch:
        watch_polling(interval_sec=args.interval, dry_run=args.dry_run); sys.exit(0)

    ap.print_help()

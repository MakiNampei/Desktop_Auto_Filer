from pathlib import Path
import shutil, csv, time

UNDO_LOG = Path("undo_log.csv")

def move_with_undo(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    final = _unique(target)
    final = Path(shutil.move(str(src), str(final)))
    _append_undo(src, final)
    return final

def undo_last():
    if not UNDO_LOG.exists(): return
    rows = UNDO_LOG.read_text(encoding="utf-8").strip().splitlines()
    if not rows: return
    ts, src_old, dst_new = rows[-1].split(",", 2)
    src_old, dst_new = Path(src_old), Path(dst_new)
    if dst_new.exists():
        back = _unique(src_old)
        back.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst_new), str(back))
    UNDO_LOG.write_text("\n".join(rows[:-1]), encoding="utf-8")

def _unique(p: Path) -> Path:
    if not p.exists(): return p
    i = 2
    stem, suf = p.stem, p.suffix
    while True:
        cand = p.with_name(f"{stem} ({i}){suf}")
        if not cand.exists(): return cand
        i += 1

def _append_undo(src: Path, dst: Path):
    new = not UNDO_LOG.exists()
    with UNDO_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["ts","src","dst"])
        w.writerow([int(time.time()), str(src), str(dst)])
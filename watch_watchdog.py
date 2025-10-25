import os, time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from desk_move import load_config, decide_destination, safe_move, append_undo, MoveRecord

class Handler(FileSystemEventHandler):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
    def on_created(self, event):
        if event.is_directory: return
        path = event.src_path
        if os.path.basename(path).startswith("."): return
        time.sleep(0.2)  
        dest = decide_destination(path, self.cfg)
        if not dest or dest == os.path.dirname(path):
            print(f"[skip] {os.path.basename(path)}")
            return
        newp = safe_move(path, dest)
        append_undo(MoveRecord(src_before=path, dst_after=newp))
        print(f"[move] {os.path.basename(path)} -> {dest}")

if __name__ == "__main__":
    cfg = load_config()
    desktop = cfg["base_dirs"]["desktop"]
    if not os.path.isdir(desktop):
        print("[!] Desktop not found"); raise SystemExit(1)
    obs = Observer()
    obs.schedule(Handler(cfg), desktop, recursive=False)
    obs.start()
    print("[watchdog] watching Desktop… Ctrl+C to stop.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()

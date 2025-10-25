from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import time

class Handler(FileSystemEventHandler):
    def __init__(self, cb): self.cb = cb
    def on_created(self, e):
        if not e.is_directory:
            time.sleep(0.3)
            self.cb(Path(e.src_path))
        print("NEW FILE EVENT:", e.src_path)

class DesktopWatcher:
    def __init__(self, desktop: Path, cb):
        self.desktop, self.cb = desktop, cb
        self.observer = Observer()
    def start(self):
        self.observer.schedule(Handler(self.cb), str(self.desktop), recursive=False)
        self.observer.start()
    def stop(self):
        self.observer.stop()
        self.observer.join()
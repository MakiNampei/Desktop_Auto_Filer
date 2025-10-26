# file_watcher.py — robust events
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import os, time, threading

class _Handler(FileSystemEventHandler):
    def __init__(self, desktop_dir: Path, callback, settle_ms=250):
        super().__init__()
        self.desktop_dir = Path(desktop_dir)
        self.callback = callback
        self.settle = settle_ms / 1000.0
        self._timers = {}  # path -> Timer

    def _maybe_schedule(self, path: Path):
        # 忽略目录、隐藏文件
        if not path or not isinstance(path, Path):
            path = Path(path)
        if path.name.startswith('.') or not path.suffix and not path.exists():
            return
        if path.is_dir():
            return

        # 去抖：同一路径短时间内变更只触发一次
        try:
            t = self._timers.pop(path, None)
            if t:
                t.cancel()
        except Exception:
            pass

        def fire():
            # 等待文件写入稳定
            time.sleep(self.settle)
            if path.exists() and path.is_file():
                try:
                    self.callback(path)
                except Exception as e:
                    print("[watcher] callback error:", e)

        timer = threading.Timer(self.settle, fire)
        self._timers[path] = timer
        timer.start()

    # 新建文件
    def on_created(self, event):
        if event.is_directory: return
        p = Path(event.src_path)
        print("[watcher] created:", p)
        self._maybe_schedule(p)

    # 写入修改（某些 app 只触发 modified）
    def on_modified(self, event):
        if event.is_directory: return
        p = Path(event.src_path)
        print("[watcher] modified:", p)
        self._maybe_schedule(p)

    # 移动/重命名（iCloud/截图常见：tmp -> 真名）
    def on_moved(self, event):
        if event.is_directory: return
        p = Path(event.dest_path)  # 关注“目标路径”
        print("[watcher] moved:", p)
        self._maybe_schedule(p)

class DesktopWatcher:
    def __init__(self, desktop_dir: Path, callback, recursive=False):
        self.desktop_dir = Path(desktop_dir)
        self.callback = callback
        self.recursive = recursive
        self.observer = Observer()
        self.handler = _Handler(self.desktop_dir, self.callback)

    def start(self):
        if not self.desktop_dir.exists():
            print("[watcher] Desktop not found:", self.desktop_dir)
            return
        print("[watcher] start on:", self.desktop_dir)
        self.observer.schedule(self.handler, str(self.desktop_dir), recursive=self.recursive)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()

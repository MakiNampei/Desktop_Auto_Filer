import os
import sys
import time
import csv
import shutil
import threading
from pathlib import Path
from queue import Queue

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PySide6 import QtCore, QtGui, QtWidgets

# ----------------- Config & Paths -----------------
AGENT_URL = os.environ.get("DESKPILOT_AGENT_URL", "http://127.0.0.1:8000")
USER_DESKTOP = Path(os.environ["USERPROFILE"]) / "Desktop"

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "DeskPilot")
os.makedirs(LOG_DIR, exist_ok=True)
MOVES_CSV = os.path.join(LOG_DIR, "moves.csv")

# ----------------- File helpers -----------------
def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def safe_move(src: Path, dst_dir: Path) -> Path:
    """Move src into dst_dir with Windows-style de-dupe (file (2).ext, ...)."""
    ensure_dir(dst_dir)
    base, ext = src.stem, src.suffix
    candidate = dst_dir / (base + ext)
    n = 2
    while candidate.exists():
        candidate = dst_dir / f"{base} ({n}){ext}"
        n += 1
    shutil.move(str(src), str(candidate))
    return candidate

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
    ts = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-ddThh:mm:ss")
    file_name = (src.name if isinstance(src, Path) else (dst.name if isinstance(dst, Path) else ""))
    suggestion_id = sug.get("suggestion_id") if sug else ""
    suggested_folder = sug.get("folder") if sug else ""
    confidence = ""
    if sug and isinstance(sug.get("confidence", None), (int, float, float.__class__)):
        confidence = f"{sug.get('confidence'):.2f}"
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

def read_move_rows() -> list[dict]:
    _moves_csv_header_if_needed()
    with open(MOVES_CSV, "r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)
    # newest first
    rows.reverse()
    return rows

# ----------------- Agent client (robust) -----------------
class AgentClient:
    def __init__(self, base=None):
        self.base = base or os.environ.get("DESKPILOT_AGENT_URL", "http://127.0.0.1:8000")
        self.s = requests.Session()
        self.s.trust_env = False  # ignore system proxies

    def _req(self, method, path, **kw):
        url = f"{self.base}{path}"
        timeout = kw.pop("timeout", 5)
        try:
            return self.s.request(method, url, timeout=timeout, **kw)
        except requests.exceptions.ConnectionError:
            alt = "http://localhost:8000" if "127.0.0.1" in self.base else "http://127.0.0.1:8000"
            r = self.s.request(method, f"{alt}{path}", timeout=timeout, **kw)
            if r.ok:
                self.base = alt
            return r

    def health(self) -> bool:
        try:
            r = self._req("GET", "/health", timeout=2)
            return r.ok and r.json().get("status") == "up"
        except Exception:
            return False

    def whitelist(self) -> list[dict]:
        r = self._req("GET", "/whitelist", timeout=5)
        r.raise_for_status()
        return r.json()["items"]

    def whitelist_add(self, path: str, description: str):
        r = self._req("POST", "/whitelist/add",
                      json={"path": path, "description": description}, timeout=5)
        r.raise_for_status()
        return r.json()

    def whitelist_remove(self, path: str):
        r = self._req("POST", "/whitelist/remove", json={"path": path}, timeout=5)
        r.raise_for_status()
        return r.json()

    def whitelist_clear(self):
        r = self._req("POST", "/whitelist/clear", json={}, timeout=5)
        r.raise_for_status()
        return r.json()

    def whitelist_reindex(self):
        r = self._req("POST", "/whitelist/reindex", json={}, timeout=10)
        r.raise_for_status()
        return r.json()

    def suggest(self, file_path: Path) -> dict:
        body = {"path": str(file_path), "name": file_path.name, "ext": file_path.suffix.lower()}
        r = self._req("POST", "/suggest", json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def feedback(self, suggestion_id: str, accepted: bool, chosen: Path | None = None):
        body = {"suggestion_id": suggestion_id, "accepted": accepted}
        if not accepted and chosen is not None:
            body["chosen_folder"] = str(chosen)
        r = self._req("POST", "/feedback", json=body, timeout=5)
        r.raise_for_status()
        return r.json()

# ----------------- Watchdog → Qt bridge -----------------
class _WDHandler(FileSystemEventHandler):
    def __init__(self, q: Queue): self.q = q
    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        # wait until stable size
        last = -1
        for _ in range(20):
            try:
                size = p.stat().st_size
            except FileNotFoundError:
                return
            if size == last:
                break
            last = size
            time.sleep(0.2)
        if p.suffix.lower() in {".tmp", ".crdownload"} or p.name.startswith("~$"):
            return
        self.q.put(p)

class WatcherThread(QtCore.QThread):
    file_ready = QtCore.Signal(Path)
    def __init__(self, watch_path: Path, parent=None):
        super().__init__(parent)
        self.watch_path = watch_path
        self.q = Queue()
        self._stop = threading.Event()
        self._obs = None
    def run(self):
        self._obs = Observer()
        self._obs.schedule(_WDHandler(self.q), str(self.watch_path), recursive=False)
        self._obs.start()
        try:
            while not self._stop.is_set():
                try:
                    path = self.q.get(timeout=0.2)
                    self.file_ready.emit(path)
                except Exception:
                    pass
        finally:
            self._obs.stop()
            self._obs.join()
    def stop(self):
        self._stop.set()

# ----------------- Whitelist Manager -----------------
class WhitelistManagerDialog(QtWidgets.QDialog):
    def __init__(self, agent: AgentClient, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.setWindowTitle("Manage Whitelist")
        self.resize(720, 360)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Description", "Path"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)

        btn_add = QtWidgets.QPushButton("Add")
        btn_del = QtWidgets.QPushButton("Delete")
        btn_clear = QtWidgets.QPushButton("Clear All")
        btn_reindex = QtWidgets.QPushButton("Reindex")
        btn_close = QtWidgets.QPushButton("Close")

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addWidget(btn_clear)
        btns.addWidget(btn_reindex)
        btns.addWidget(btn_close)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(btns)

        btn_add.clicked.connect(self.on_add)
        btn_del.clicked.connect(self.on_del)
        btn_clear.clicked.connect(self.on_clear)
        btn_reindex.clicked.connect(self.on_reindex)
        btn_close.clicked.connect(self.accept)

        self.refresh()

    def refresh(self):
        try:
            items = self.agent.whitelist()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Failed to load whitelist:\n{e}")
            return
        self.table.setRowCount(0)
        for it in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(it.get("description", "")))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(it["path"]))

    def on_add(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a folder to whitelist")
        if not path:
            return
        desc, ok = QtWidgets.QInputDialog.getText(self, "Description", "Short description:", text=Path(path).name)
        if not ok:
            return
        try:
            self.agent.whitelist_add(path, desc or Path(path).name)
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Add failed:\n{e}")

    def on_del(self):
        r = self.table.currentRow()
        if r < 0:
            return
        path = self.table.item(r, 1).text()
        try:
            self.agent.whitelist_remove(path)
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Delete failed:\n{e}")

    def on_clear(self):
        if QtWidgets.QMessageBox.question(self, "Confirm", "Clear ALL whitelist items?") != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.agent.whitelist_clear()
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Clear failed:\n{e}")

    def on_reindex(self):
        try:
            self.agent.whitelist_reindex()
            QtWidgets.QMessageBox.information(self, "Reindex", "Rebuilt embedding index (if available).")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Reindex failed:\n{e}")

# ----------------- Whitelist picker -----------------
class WhitelistPicker(QtWidgets.QDialog):
    def __init__(self, agent: AgentClient, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.setWindowTitle("Choose destination (whitelist)")
        self.resize(700, 360)
        self.selected_path = None

        self.list = QtWidgets.QListWidget()
        self.list.itemDoubleClicked.connect(self.accept)

        btn_ok = QtWidgets.QPushButton("OK")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.list)
        hb = QtWidgets.QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(btn_cancel)
        hb.addWidget(btn_ok)
        lay.addLayout(hb)

        self.refresh()

    def refresh(self):
        self.list.clear()
        try:
            items = self.agent.whitelist()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Agent", f"Failed to load whitelist:\n{e}")
            return
        for it in items:
            txt = f"{it.get('description','(no desc)')} — {it['path']}"
            li = QtWidgets.QListWidgetItem(txt)
            li.setData(QtCore.Qt.ItemDataRole.UserRole, it["path"])
            self.list.addItem(li)

    def accept(self):
        it = self.list.currentItem()
        if not it:
            super().reject()
            return
        self.selected_path = it.data(QtCore.Qt.ItemDataRole.UserRole)
        super().accept()

# ----------------- File Pilot Dialog -----------------
class FilePilotDialog(QtWidgets.QDialog):
    def __init__(self, agent: AgentClient, file_path: Path, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.file_path = file_path
        self.suggestion = None

        self.setWindowTitle("DeskPilot — File Pilot")
        self.resize(780, 380)

        self.lbl_name = QtWidgets.QLabel()
        self.lbl_from = QtWidgets.QLabel()
        self.lbl_suggest = QtWidgets.QLabel()
        self.lbl_conf = QtWidgets.QLabel()
        self.txt_because = QtWidgets.QTextEdit()
        self.txt_because.setReadOnly(True)
        self.txt_because.setMinimumHeight(100)

        btn_open = QtWidgets.QPushButton("Open")
        btn_show = QtWidgets.QPushButton("Show in Explorer")
        btn_open.clicked.connect(self.on_open)
        btn_show.clicked.connect(self.on_show)

        btn_accept = QtWidgets.QPushButton("Accept")
        btn_decline = QtWidgets.QPushButton("Decline")
        btn_ignore = QtWidgets.QPushButton("Ignore")
        btn_accept.setDefault(True)

        btn_accept.clicked.connect(self.on_accept)
        btn_decline.clicked.connect(self.on_decline)
        btn_ignore.clicked.connect(self.reject)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Name:"), 0, 0)
        grid.addWidget(self.lbl_name, 0, 1)
        grid.addWidget(QtWidgets.QLabel("From:"), 1, 0)
        grid.addWidget(self.lbl_from, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Suggested folder:"), 2, 0)
        grid.addWidget(self.lbl_suggest, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Confidence:"), 3, 0)
        grid.addWidget(self.lbl_conf, 3, 1)
        grid.addWidget(QtWidgets.QLabel("Because:"), 4, 0, 1, 2)
        grid.addWidget(self.txt_because, 5, 0, 1, 2)
        hb = QtWidgets.QHBoxLayout()
        hb.addWidget(btn_open)
        hb.addWidget(btn_show)
        hb.addStretch(1)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(btn_ignore)
        btns.addWidget(btn_decline)
        btns.addWidget(btn_accept)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addLayout(hb)
        lay.addSpacing(10)
        lay.addLayout(btns)

        self.populate()

    def populate(self):
        self.lbl_name.setText(self.file_path.name)
        self.lbl_from.setText(str(self.file_path.parent))
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()
        try:
            self.suggestion = self.agent.suggest(self.file_path)
        except Exception as e:
            self.suggestion = None
            QtWidgets.QMessageBox.warning(self, "Agent", f"Suggest failed:\n{e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if not self.suggestion:
            self.lbl_suggest.setText("(no suggestion)")
            self.lbl_conf.setText("-")
            self.txt_because.setPlainText("")
            return

        self.lbl_suggest.setText(self.suggestion["folder"])
        self.lbl_conf.setText(f"{self.suggestion['confidence']:.2f}")
        self.txt_because.setPlainText(self.suggestion.get("rationale", ""))

        if self.suggestion.get("needs_whitelist"):
            QtWidgets.QMessageBox.information(self, "Whitelist",
                "No whitelist configured yet. Open Manage Whitelist from the main window.")

    def on_open(self):
        try: os.startfile(str(self.file_path))
        except Exception: pass

    def on_show(self):
        try: os.startfile(str(self.file_path.parent))
        except Exception: pass

    def on_accept(self):
        if not self.suggestion:
            self.reject(); return
        try:
            newp = safe_move(self.file_path, Path(self.suggestion["folder"]))
            log_move("accept", self.file_path, newp, self.suggestion, True)
            self.agent.feedback(self.suggestion["suggestion_id"], True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Move", f"Move failed:\n{e}")
            return
        self.accept()

    def on_decline(self):
        if not self.suggestion:
            self.reject(); return
        picker = WhitelistPicker(self.agent, self)
        if picker.exec() != QtWidgets.QDialog.Accepted or not picker.selected_path:
            log_move("choose_cancel", self.file_path, None, self.suggestion, None)
            return
        dest = Path(os.path.expandvars(os.path.expanduser(picker.selected_path)))
        try:
            newp = safe_move(self.file_path, dest)
            log_move("choose", self.file_path, newp, self.suggestion, False)
            self.agent.feedback(self.suggestion["suggestion_id"], False, dest)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Move", f"Move failed:\n{e}")
            return
        self.accept()

# ----------------- Log Viewer (with per-row Undo) -----------------
class LogViewerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Move Log")
        self.resize(1000, 520)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Time", "Action", "File", "From", "To", "Rationale", "Undo"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_close = QtWidgets.QPushButton("Close")
        btn_refresh.clicked.connect(self.refresh)
        btn_close.clicked.connect(self.accept)

        hb = QtWidgets.QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(btn_refresh)
        hb.addWidget(btn_close)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(hb)

        self.refresh()

    def refresh(self):
        rows = read_move_rows()
        self.table.setRowCount(0)
        for r in rows:
            self._append_row(r)

    def _append_row(self, row: dict):
        i = self.table.rowCount()
        self.table.insertRow(i)

        def _item(text):
            it = QtWidgets.QTableWidgetItem(text or "")
            it.setToolTip(text or "")
            return it

        self.table.setItem(i, 0, _item(row.get("timestamp")))
        self.table.setItem(i, 1, _item(row.get("action")))
        self.table.setItem(i, 2, _item(row.get("file_name")))
        self.table.setItem(i, 3, _item(row.get("src_path")))
        self.table.setItem(i, 4, _item(row.get("dst_path")))
        self.table.setItem(i, 5, _item(row.get("rationale")))

        # Only rows that actually moved a file are undoable
        undoable = row.get("action") in {"accept", "choose"} and row.get("dst_path")
        btn = QtWidgets.QPushButton("Undo")
        btn.setEnabled(bool(undoable))
        if undoable:
            btn.clicked.connect(lambda _=None, rr=row: self._undo_row(rr))
        self.table.setCellWidget(i, 6, btn)

    def _undo_row(self, row: dict):
        src_before = Path(row.get("src_path") or "")
        dst_after = Path(row.get("dst_path") or "")
        if not dst_after.exists():
            QtWidgets.QMessageBox.warning(self, "Undo", "File not found at the logged destination; it may have been moved or deleted.")
            return
        target = src_before.parent if src_before and src_before.parent.exists() else USER_DESKTOP
        try:
            restored = safe_move(dst_after, target)
            log_move("undo", Path(row.get("dst_path")), restored, None, None, note="undo via UI")
            QtWidgets.QMessageBox.information(self, "Undo", f"Restored to:\n{restored}")
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Undo", f"Undo failed:\n{e}")

# ----------------- Main Window -----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.agent = AgentClient()
        self.setWindowTitle("DeskPilot")
        self.resize(820, 420)

        title = QtWidgets.QLabel("DeskPilot")
        subtitle = QtWidgets.QLabel("Smart Desktop File Assistant")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size: 36px; font-weight: 700;")
        subtitle.setStyleSheet("font-size: 16px; color: gray;")

        btn_wl = QtWidgets.QPushButton("Manage Whitelist")
        btn_log = QtWidgets.QPushButton("See Move Log")
        btn_wl.setMinimumWidth(200)
        btn_log.setMinimumWidth(200)
        btn_wl.clicked.connect(self.open_whitelist)
        btn_log.clicked.connect(self.open_log)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(title, 0, 0, 1, 2)
        grid.addWidget(subtitle, 1, 0, 1, 2)
        grid.addItem(QtWidgets.QSpacerItem(10, 20), 2, 0)
        grid.addWidget(btn_wl, 3, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(btn_log, 3, 1, QtCore.Qt.AlignmentFlag.AlignLeft)

        central = QtWidgets.QWidget()
        central.setLayout(grid)
        self.setCentralWidget(central)

        # Status bar
        self.status = self.statusBar()
        self.lbl_status = QtWidgets.QLabel("")
        self.status.addPermanentWidget(self.lbl_status)
        self.update_status()

        # Tray (optional)
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QtWidgets.QSystemTrayIcon(self)
            self.tray.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon))
            m = QtWidgets.QMenu()
            act_show = m.addAction("Show")
            act_show.triggered.connect(self.showNormal)
            act_quit = m.addAction("Quit")
            act_quit.triggered.connect(QtWidgets.QApplication.instance().quit)
            self.tray.setContextMenu(m)
            self.tray.show()
        else:
            self.tray = None

        # Watcher
        USER_DESKTOP.mkdir(parents=True, exist_ok=True)
        self.watcher = WatcherThread(USER_DESKTOP, self)
        self.watcher.file_ready.connect(self.on_file_ready)
        self.watcher.start()

        # Health poll
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(3000)

    def update_status(self):
        ok = self.agent.health()
        s = f"Watching: {USER_DESKTOP}   |   Agent: {'Connected' if ok else 'Offline'}"
        self.lbl_status.setText(s)

    def open_whitelist(self):
        WhitelistManagerDialog(self.agent, self).exec()

    def open_log(self):
        LogViewerDialog(self).exec()

    @QtCore.Slot(Path)
    def on_file_ready(self, path: Path):
        FilePilotDialog(self.agent, path, self).exec()

    def closeEvent(self, e: QtGui.QCloseEvent):
        if self.tray:
            self.hide()
            e.ignore()
        else:
            self.watcher.stop()
            self.watcher.wait()
            e.accept()

# ----------------- Main -----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DeskPilot")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

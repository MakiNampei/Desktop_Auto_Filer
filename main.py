# main.py — thread-safe, PySide6
from pathlib import Path
import sys
from PySide6 import QtWidgets, QtGui, QtCore

from rule_engine import RuleEngine
from file_watcher import DesktopWatcher
from ui_chip import SuggestionChip
from actions import move_with_undo, undo_last

RULES_PATH = Path(__file__).parent / "rules.json"


def _make_debug_icon() -> QtGui.QIcon:
    pix = QtGui.QPixmap(18, 18)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.red))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 16, 16)
    p.end()
    return QtGui.QIcon(pix)


class TrayApp(QtWidgets.QSystemTrayIcon):
    # 由 watchdog 线程发射，主线程接收
    newFileSignal = QtCore.Signal(Path)

    def __init__(self, app: QtWidgets.QApplication):
        print("[TrayApp] init begin", flush=True)
        app.setQuitOnLastWindowClosed(False)

        icon = _make_debug_icon()
        super().__init__(icon, app)
        self.setIcon(icon)
        self.setToolTip("Desktop Auto-Filer")
        print("[TrayApp] tray available:", QtWidgets.QSystemTrayIcon.isSystemTrayAvailable(), flush=True)
        self.show()
        self.setVisible(True)
        print("[TrayApp] tray visible after show():", self.isVisible(), flush=True)

        # 菜单
        menu = QtWidgets.QMenu()
        test = menu.addAction("Test Popup")
        test.triggered.connect(self._test_popup)
        menu.addSeparator()
        undo_act = menu.addAction("Undo Last Move")
        undo_act.triggered.connect(lambda: (undo_last(), self.showMessage("Undo", "Undid last move")))
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(QtWidgets.QApplication.quit)
        self.setContextMenu(menu)

        self._dlgs = []

        # 规则/监听
        self.engine = RuleEngine(RULES_PATH)
        self.newFileSignal.connect(
            self._handle_new_file,
            QtCore.Qt.ConnectionType.QueuedConnection,   # 关键：排队到主线程
        )

        self.watcher = DesktopWatcher(self.engine.base["desktop"], self.on_new_file)
        print("[TrayApp] Watching desktop at:", self.engine.base["desktop"], flush=True)
        self.watcher.start()
        print("[TrayApp] watcher started", flush=True)

    # —— 在 watchdog 线程里被调用：只发信号，不做 Qt 操作
    def on_new_file(self, file_path: Path):
        print("[TrayApp] on_new_file (worker thread):", file_path, flush=True)
        self.newFileSignal.emit(file_path)

    # —— 主线程槽：安全地做一切 UI
    @QtCore.Slot(Path)
    def _handle_new_file(self, file_path: Path):
        print("[TrayApp] handle_new_file (main thread):", file_path, flush=True)
        # 忽略隐藏/临时名（.Screenshot ...）
        if file_path.name.startswith("."):
            return
        if not file_path.exists() or not file_path.is_file():
            return

        p = self.engine.propose(file_path)

        # 轻微延迟可让文件写入更稳定（必要时增大到 500–800ms）
        QtCore.QTimer.singleShot(200, lambda: self._show_chip(file_path, p))

    def _test_popup(self):
        print("[TrayApp] Test Popup clicked", flush=True)
        fake = self.engine.base["desktop"] / "fake_demo.txt"
        p = self.engine.propose(fake)
        self._show_chip(fake, p)

    def _show_chip(self, file_path: Path, p):
        print("[TrayApp] show_chip for:", file_path, "→", p.dest_path, flush=True)
        dlg = SuggestionChip(file_path, p.dest_path, p.why, p.confidence)

        def do_move(dest_dir: Path):
            print("[TrayApp] do_move →", dest_dir, flush=True)
            final = move_with_undo(file_path, dest_dir)
            self.showMessage("Moved", f"Moved to: {final}")
            dlg.close()

        def choose_other():
            print("[TrayApp] choose_other", flush=True)
            d = QtWidgets.QFileDialog.getExistingDirectory(None, "Choose Destination", str(p.dest_path))
            if d:
                do_move(Path(d))

        dlg.acceptedMove.connect(do_move)
        dlg.rejectedChoose.connect(choose_other)
        dlg.whyAsked.connect(lambda: QtWidgets.QMessageBox.information(None, "Why?", p.why or "N/A"))
        dlg.undoAsked.connect(lambda: (undo_last(), self.showMessage("Undo", "Undid last move")))

        dlg.adjustSize()
        screen_geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        center = screen_geo.center()
        dlg.move(center.x() - dlg.width() // 2, center.y() - dlg.height() // 2)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

        self._dlgs.append(dlg)
        dlg.finished.connect(lambda _: self._dlgs.remove(dlg))

def main():
    print("[BOOT] creating QApplication", flush=True)
    app = QtWidgets.QApplication(sys.argv)
    tray = TrayApp(app)
    tray.show()
    print("[BOOT] entering Qt event loop", flush=True)
    sys.exit(app.exec())

if __name__ == "__main__":
    print("[BOOT] entering main.py", flush=True)
    main()

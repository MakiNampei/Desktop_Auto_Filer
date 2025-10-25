import sys
from pathlib import Path
from PyQt6 import QtWidgets, QtGui, QtCore
from rule_engine import RuleEngine
from file_watcher import DesktopWatcher
from ui_chip import SuggestionChip
from actions import move_with_undo, undo_last

def _make_debug_icon() -> QtGui.QIcon:
    # 生成一个 18x18 的实心图标（白色状态栏下也能看清）
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
    def __init__(self, app: QtWidgets.QApplication):
        app.setQuitOnLastWindowClosed(False)

        icon = _make_debug_icon()  # ✅ 明确可见的红点图标
        super().__init__(icon, app)
        self.setIcon(icon)
        self.setToolTip("Desktop Auto-Filer")

        # 诊断：托盘是否可用/是否显示
        print("Tray available:", QtWidgets.QSystemTrayIcon.isSystemTrayAvailable())
        self.show()
        self.setVisible(True)
        print("Tray visible after show():", self.isVisible())

        # 托盘菜单 + 测试按钮（不用等监听）
        menu = QtWidgets.QMenu()
        test = menu.addAction("Test Popup")
        test.triggered.connect(self._test_popup)
        menu.addSeparator()
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(QtWidgets.QApplication.quit)
        self.setContextMenu(menu)

        self._dlgs = []

        # 正常初始化
        self.engine = RuleEngine(RULES_PATH)
        self.watcher = DesktopWatcher(self.engine.base["desktop"], self.on_new_file)
        print("Watching desktop at:", self.engine.base["desktop"])
        self.watcher.start()

    def _test_popup(self):
        fake = self.engine.base["desktop"] / "fake_demo.txt"
        p = self.engine.propose(fake)
        self._show_chip(fake, p)

    def on_new_file(self, file_path: Path):
        print("WILL SHOW CHIP FOR:", file_path)
        p = self.engine.propose(file_path)
        QtCore.QTimer.singleShot(0, lambda: self._show_chip(file_path, p))  # 回到主线程

    def _show_chip(self, file_path: Path, p):
        from ui_chip import SuggestionChip
        dlg = SuggestionChip(file_path, p.dest_path, p.why, p.confidence)

        def do_move(dest_dir: Path):
            final = move_with_undo(file_path, dest_dir)
            self.showMessage("Moved", f"已移动到：{final}")
            dlg.close()

        def choose_other():
            d = QtWidgets.QFileDialog.getExistingDirectory(None, "选择目标文件夹", str(p.dest_path))
            if d: do_move(Path(d))

        dlg.acceptedMove.connect(do_move)
        dlg.rejectedChoose.connect(choose_other)
        dlg.whyAsked.connect(lambda: QtWidgets.QMessageBox.information(None, "Why?", p.why or "无"))
        dlg.undoAsked.connect(lambda: (undo_last(), self.showMessage("Undo", "已撤销最近一次移动")))

        # 先居中显示，确保能看到
        dlg.adjustSize()
        screen_geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        center = screen_geo.center()
        dlg.move(center.x() - dlg.width()//2, center.y() - dlg.height()//2)
        dlg.show(); dlg.raise_(); dlg.activateWindow()

        self._dlgs.append(dlg)
        dlg.finished.connect(lambda _: self._dlgs.remove(dlg))

def main():
    app = QtWidgets.QApplication(sys.argv)
    tray = TrayApp(app)
    tray.show()

    # ✅ 托盘不可见时，弹出临时控制面板，先让你能点“Test Popup”
    if not tray.isVisible():
        w = QtWidgets.QWidget()
        w.setWindowTitle("Desktop Auto-Filer（临时控制面板）")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("托盘不可见。点下面按钮手动测试弹窗："))
        btn = QtWidgets.QPushButton("Test Popup")
        btn.clicked.connect(tray._test_popup)
        lay.addWidget(btn)
        w.setWindowFlag(QtCore.Qt.WindowType.Tool)
        w.show()
        tray._fallback_window = w  # 保存引用，避免被回收

    sys.exit(app.exec())
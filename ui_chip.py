# ui_chip.py — PySide6 version
from pathlib import Path

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Signal
from PySide6.QtGui import QShortcut, QKeySequence


class SuggestionChip(QtWidgets.QDialog):
    # ---- PySide6 uses `Signal`, not `pyqtSignal`
    acceptedMove = Signal(Path)
    rejectedChoose = Signal()
    whyAsked = Signal()
    undoAsked = Signal()

    def __init__(self, file_path: Path, dest_dir: Path, why: str, conf: float):
        super().__init__()
        self.file_path = file_path
        self.dest_dir = dest_dir  # keep for shortcuts/callbacks

        self.setWindowTitle("Desktop Auto-Filer")
        # Tool + AlwaysOnTop → macOS 更容易前置显示
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )

        # --- content
        lbl = QtWidgets.QLabel(
            f"📄 <b>{file_path.name}</b><br>"
            f"➡️ Suggest move to: <code>{dest_dir}</code><br>"
            f"Confidence: {int(conf*100)}%"
        )
        lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)

        b_move = QtWidgets.QPushButton("Move")
        b_no   = QtWidgets.QPushButton("No")
        b_why  = QtWidgets.QPushButton("Why?")
        b_undo = QtWidgets.QPushButton("Undo")

        b_move.clicked.connect(lambda: self.acceptedMove.emit(dest_dir))
        b_no.clicked.connect(self.rejectedChoose.emit)
        b_why.clicked.connect(self.whyAsked.emit)
        b_undo.clicked.connect(self.undoAsked.emit)

        # --- layout
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(lbl)
        row = QtWidgets.QHBoxLayout()
        for b in (b_move, b_no, b_why, b_undo):
            row.addWidget(b)
        lay.addLayout(row)

        # --- shortcuts (Enter = Move, Esc = Close)
        QShortcut(QKeySequence("Return"), self, activated=lambda: self.acceptedMove.emit(self.dest_dir))
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

        # 非模态，允许前置
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()

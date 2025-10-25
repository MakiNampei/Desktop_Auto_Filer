from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtGui import QShortcut, QKeySequence
from pathlib import Path

class SuggestionChip(QtWidgets.QDialog):
    acceptedMove = QtCore.pyqtSignal(Path)
    rejectedChoose = QtCore.pyqtSignal()
    whyAsked = QtCore.pyqtSignal()
    undoAsked = QtCore.pyqtSignal()
    def __init__(self, file_path: Path, dest_dir: Path, why: str, conf: float):
        super().__init__()
        self.setWindowTitle("Desktop Auto-Filer")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.FramelessWindowHint)
        lbl = QtWidgets.QLabel(f"建议移动到：{dest_dir}\n文件：{file_path.name}\n置信度：{int(conf*100)}%")
        b1, b2, b3, b4 = [QtWidgets.QPushButton(x) for x in ("Move","No","Why?","Undo")]
        b1.clicked.connect(lambda: self.acceptedMove.emit(dest_dir))
        b2.clicked.connect(self.rejectedChoose.emit)
        b3.clicked.connect(self.whyAsked.emit)
        b4.clicked.connect(self.undoAsked.emit)
        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(lbl)
        row = QtWidgets.QHBoxLayout(); [row.addWidget(b) for b in (b1,b2,b3,b4)]
        lay.addLayout(row)
        QShortcut(QKeySequence("Return"), self, activated=lambda: self.acceptedMove.emit(self.dest_dir))
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
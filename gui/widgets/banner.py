"""虚拟化未开启警告横幅：橙色警示 + 一键打开中文教程。"""
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from gui.i18n import bind, tr

# 警示色（品牌核心色，主题通用）
WARNING_COLOR = "#FF7D00"


class WarningBanner(QWidget):
    """顶部警告横幅（objectName=banner，主题 QSS 定义边框样式）。"""

    action_requested = Signal()
    closed = Signal()

    def __init__(self, text_key: str, action_key: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        self._icon = QLabel("⚠")
        self._icon.setStyleSheet(f"color: {WARNING_COLOR}; font-size: 16px;")
        self._icon.setFixedWidth(20)

        self._label = QLabel()
        self._label.setStyleSheet("border: none; background: transparent;")
        self._label.setWordWrap(True)
        bind(self._label, text_key)

        self._action = QPushButton()
        self._action.setObjectName("danger")
        self._action.setCursor(Qt.CursorShape.PointingHandCursor)
        bind(self._action, action_key)
        self._action.clicked.connect(self.action_requested.emit)

        self._close = QPushButton("×")
        self._close.setFixedSize(24, 24)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.clicked.connect(self._on_close)

        layout.addWidget(self._icon)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._action)
        layout.addWidget(self._close)

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

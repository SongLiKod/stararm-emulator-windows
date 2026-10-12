"""实例状态徽章：运行中（青绿）/ 已停止（灰）/ 启动中（蓝）/ 错误（橙红）。"""
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from gui.i18n import tr

# 主题通用主色
SUCCESS_COLOR = "#36CFC9"
PRIMARY_COLOR = "#1677FF"
WARNING_COLOR = "#FF7D00"
GRAY = "#86909C"

STATE_KEYS = {
    "running": ("state_running", SUCCESS_COLOR),
    "stopped": ("state_stopped", GRAY),
    "starting": ("state_starting", PRIMARY_COLOR),
    "stopping": ("state_stopping", GRAY),
    "error": ("state_error", WARNING_COLOR),
}


class StatusBadge(QWidget):
    """状态圆点 + 文本。"""

    def __init__(self, state: str = "stopped", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setStyleSheet("border-radius: 5px; border: none; background: transparent;")
        self._text = QLabel()
        self._text.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        layout.addStretch(1)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        key, color = STATE_KEYS.get(state, ("state_unknown", GRAY))
        self._dot.setStyleSheet(
            f"border-radius: 5px; border: none; background: {color};")
        self._text.setText(tr(key))

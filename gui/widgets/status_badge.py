"""实例状态徽章：胶囊底色 + 状态圆点（运行中青绿 / 已停止灰 / 启动中蓝 / 错误橙红）。"""
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


def _tint(hex_color: str, alpha: int = 40) -> str:
    """把 #RRGGBB 转成带透明度的胶囊底色 rgba(...)。"""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    return f"rgba({r}, {g}, {b}, {alpha})"


class StatusBadge(QWidget):
    """状态胶囊：底色 + 圆点 + 文本。"""

    def __init__(self, state: str = "stopped", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 纯 QWidget 需要该属性，胶囊底色才能生效
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._text = QLabel()
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        layout.addStretch(1)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        key, color = STATE_KEYS.get(state, ("state_unknown", GRAY))
        self.setStyleSheet(
            f"background-color: {_tint(color)}; border: none; border-radius: 10px;")
        self._dot.setStyleSheet(
            f"border-radius: 4px; border: none; background: {color};")
        self._text.setStyleSheet("border: none; background: transparent;")
        self._text.setText(tr(key))

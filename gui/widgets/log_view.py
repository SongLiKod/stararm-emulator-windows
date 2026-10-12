"""系统日志查看面板：系统日志 / 运行日志 / 错误日志三类，实时刷新 + 双语渲染。"""
from collections import deque
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from gui.i18n import RETRANSLATOR, bind, tr
from log.logger import LogCategory, LogEntry, get_logger

MAX_ENTRIES = 500


class LogView(QWidget):
    """单类别日志视图（实时追加，语言切换时整体重渲）。"""

    def __init__(self, category: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._category = category
        self._entries = deque(maxlen=MAX_ENTRIES)
        self._level_filter = "ALL"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        bar = QHBoxLayout()
        self._filter = QComboBox()
        for level in ("ALL", "INFO", "WARNING", "ERROR"):
            self._filter.addItem(level, level)
        self._filter.currentIndexChanged.connect(self._render)
        self._count_label = QLabel("")
        self._count_label.setObjectName("secondary")
        self._export_btn = QPushButton()
        bind(self._export_btn, "btn_export_log")
        self._export_btn.clicked.connect(self._export)
        self._clear_btn = QPushButton()
        bind(self._clear_btn, "btn_clear_log")
        self._clear_btn.clicked.connect(self._clear)
        bar.addWidget(self._filter)
        bar.addStretch(1)
        bar.addWidget(self._count_label)
        bar.addWidget(self._export_btn)
        bar.addWidget(self._clear_btn)
        layout.addLayout(bar)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_ENTRIES)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._view)

        get_logger().add_listener(self._on_entry)
        RETRANSLATOR.language_changed.connect(self._render)
        # 打开时回填历史
        for entry in get_logger().recent(self._category, limit=MAX_ENTRIES):
            self._entries.append(entry)
        self._render()

    # ------------------------------------------------------------- events
    def _on_entry(self, entry: LogEntry) -> None:
        if entry.category != self._category:
            return
        self._entries.append(entry)
        if self._passes_filter(entry):
            self._view.appendPlainText(self._line(entry))
            self._count_label.setText(str(len(self._entries)))

    # ------------------------------------------------------------- render
    def _passes_filter(self, entry: LogEntry) -> bool:
        return self._level_filter == "ALL" or entry.level.value == self._level_filter

    def _line(self, entry: LogEntry) -> str:
        return f"{entry.time_text()} [{entry.level.value}] {entry.text()}"

    def _render(self, *_args) -> None:
        lines = [self._line(e) for e in self._entries if self._passes_filter(e)]
        self._view.setPlainText("\n".join(lines))
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._count_label.setText(str(len(self._entries)))

    # ------------------------------------------------------------- actions
    def _clear(self) -> None:
        self._entries.clear()
        self._view.clear()
        self._count_label.setText("0")

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, tr("msg_save_log"), f"{self._category}.log", "Log (*.log)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._view.toPlainText())


class LogPanel(QWidget):
    """日志面板：系统 / 运行 / 错误三类选项卡。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QTabWidget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._views = {
            LogCategory.SYSTEM: LogView(LogCategory.SYSTEM),
            LogCategory.RUN: LogView(LogCategory.RUN),
            LogCategory.ERROR: LogView(LogCategory.ERROR),
        }
        titles = {
            LogCategory.SYSTEM: "tab_log_system",
            LogCategory.RUN: "tab_log_run",
            LogCategory.ERROR: "tab_log_error",
        }
        for category, view in self._views.items():
            self._tabs.addTab(view, tr(titles[category]))
        RETRANSLATOR.language_changed.connect(lambda _lang: self._retranslate())
        layout.addWidget(self._tabs)

    def _retranslate(self) -> None:
        titles = {
            LogCategory.SYSTEM: "tab_log_system",
            LogCategory.RUN: "tab_log_run",
            LogCategory.ERROR: "tab_log_error",
        }
        for index in range(self._tabs.count()):
            category = list(self._views.keys())[index]
            self._tabs.setTabText(index, tr(titles[category]))

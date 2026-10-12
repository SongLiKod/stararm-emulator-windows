"""GUI 应用入口：QApplication 装配（主题、语言、高 DPI、主窗口）。"""
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from config.i18n import get_translator
from core.service import StarARMService
from gui.i18n import RETRANSLATOR
from gui.main_window import MainWindow
from gui.theme import ThemeManager
from log.logger import get_logger


def run() -> int:
    # 高 DPI 支持（Qt6 默认开启）
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setOrganizationName("StarARM")
    app.setApplicationName("StarARM Emulator")
    app.setStyle("Fusion")

    # 核心服务（全局配置 / 语言跟随系统 / 日志）
    service = StarARMService()

    # 主题（跟随系统 / 浅色 / 深色；用户选择持久化，重启不重置）
    theme = ThemeManager(service.settings)
    theme.apply(app)

    window = MainWindow(service, theme)
    window.show()

    # 语言切换实时生效（无 GUI 重启）
    RETRANSLATOR.retranslate()

    logger = get_logger()
    logger.system("log_gui_ready")
    return app.exec()

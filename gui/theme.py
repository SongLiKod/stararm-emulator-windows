"""主题管理：三套主题模式（跟随系统 / 浅色 / 深色）。

- 配色严格按产品视觉规范（resource/themes/*.json）
- 跟随系统：实时读取 Windows 系统主题配置（注册表 AppsUseLightTheme），
  系统切换深浅色时实时动态适配
- 用户选择持久化保存（重启不重置），切换实时生效（无需重启软件）
"""
import os
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from config.i18n import get_translator
from config.settings import SettingsManager
from config.theme import build_qss, load_all_themes


def windows_system_is_light() -> bool:
    """实时读取 Windows 系统主题：返回系统当前是否为浅色模式。"""
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(value) == 1
            finally:
                winreg.CloseKey(key)
        except OSError:
            return True
    return True


class ThemeManager(QObject):
    theme_changed = Signal(str)  # 解析后的主题："light" | "dark"

    def __init__(self, settings: SettingsManager, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._themes = load_all_themes()
        self._resolved = self._resolve(settings.get().theme_mode)
        settings.add_listener(self._on_setting_changed)

    # ------------------------------------------------------------- resolve
    def _resolve(self, mode: str) -> str:
        if mode in ("light", "dark"):
            return mode
        return "light" if windows_system_is_light() else "dark"

    @property
    def resolved(self) -> str:
        return self._resolved

    @property
    def mode(self) -> str:
        return self._settings.get().theme_mode

    def palette(self) -> dict:
        return self._themes[self._resolved]

    # ------------------------------------------------------------- switch
    def set_mode(self, mode: str) -> None:
        """用户切换主题：持久化保存 + 实时生效。"""
        self._settings.update(theme_mode=mode)

    def _on_setting_changed(self, key: str, value: object) -> None:
        if key == "theme_mode":
            self._resolved = self._resolve(str(value))
            self.apply()

    def poll_system(self) -> bool:
        """跟随系统模式的实时动态适配；主题变化返回 True（供定时器触发重刷）。"""
        if self._settings.get().theme_mode != "system":
            return False
        resolved = self._resolve("system")
        if resolved != self._resolved:
            self._resolved = resolved
            self.apply()
            return True
        return False

    # ------------------------------------------------------------- apply
    def apply(self, app: Optional[QApplication] = None) -> None:
        app = app or QApplication.instance()
        if app is None:
            return
        app.setStyleSheet(build_qss(self.palette()))
        self.theme_changed.emit(self._resolved)


def theme_name_for_display(mode: str) -> str:
    return get_translator().tr(f"theme_{mode}")

"""星模ARM原生安卓模拟器（StarARM Emulator）全局配置层。

包含：路径解析、固定常量、全局设置、主题配色、语言包加载。
本层不依赖任何 GUI 框架，供 GUI 与 CLI（无界面后台运维）共用。
"""
from config.paths import app_data_dir, repo_root, resource_dir
from config.constants import (
    APP_NAME_ZH,
    APP_NAME_EN,
    VERSION,
    RESOLUTION_PRESETS,
    DEFAULT_RESOLUTION,
    DEFAULT_DPI,
    DPI_MIN,
    DPI_MAX,
    NETWORK_MODES,
    GRAPHICS_MODES,
    ANDROID_VERSIONS,
    ADB_PORT_RANGE,
    VNC_DISPLAY_RANGE,
    AGENT_PORT_RANGE,
)
from config.settings import GlobalSettings, SettingsManager
from config.i18n import Translator, get_translator, system_language
from config.theme import load_theme, load_all_themes, build_qss, THEME_MODES

__all__ = [
    "app_data_dir", "repo_root", "resource_dir",
    "APP_NAME_ZH", "APP_NAME_EN", "VERSION",
    "RESOLUTION_PRESETS", "DEFAULT_RESOLUTION", "DEFAULT_DPI", "DPI_MIN", "DPI_MAX",
    "NETWORK_MODES", "GRAPHICS_MODES", "ANDROID_VERSIONS",
    "ADB_PORT_RANGE", "VNC_DISPLAY_RANGE", "AGENT_PORT_RANGE",
    "GlobalSettings", "SettingsManager",
    "Translator", "get_translator", "system_language",
    "load_theme", "load_all_themes", "build_qss", "THEME_MODES",
]

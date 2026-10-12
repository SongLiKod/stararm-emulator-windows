"""全局设置：主题模式、语言、全局资源阈值、外部组件路径。

设置持久化于用户数据目录 settings.json，重启不重置。
"""
import json
import threading
from dataclasses import dataclass, asdict
from typing import Callable, Dict, List, Optional

from config import paths

VALID_THEME_MODES = ("system", "light", "dark")
VALID_LANGUAGES = ("system", "zh_CN", "en_US")
VALID_NETWORK_MODES = ("nat", "bridge")
VALID_GRAPHICS_MODES = ("virgl-vulkan", "virgl", "software")


@dataclass
class GlobalSettings:
    theme_mode: str = "system"      # 跟随系统 / 浅色 / 深色
    language: str = "system"        # 跟随系统 / 简体中文 / 英文
    max_instances: int = 8          # 全局最大实例数（资源超限保护）
    max_total_cpu_cores: int = 0    # 0 = 按主机自动
    max_total_memory_gb: int = 0    # 0 = 按主机自动
    qemu_path: str = ""             # 留空自动查找
    adb_path: str = ""              # 留空自动查找
    image_source: str = ""          # 内置镜像下载源 URL（留空则需手动导入）
    shared_folder: str = ""         # 共享文件夹（留空用默认目录）

    def validate(self) -> None:
        if self.theme_mode not in VALID_THEME_MODES:
            raise ValueError("invalid theme_mode")
        if self.language not in VALID_LANGUAGES:
            raise ValueError("invalid language")
        if self.max_instances < 1:
            raise ValueError("invalid max_instances")
        if self.max_total_cpu_cores < 0 or self.max_total_memory_gb < 0:
            raise ValueError("invalid resource thresholds")


class SettingsManager:
    """全局设置管理：加载、保存、更新（带变更回调）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: List[Callable[[str, object], None]] = []
        self._settings = GlobalSettings()
        self.load()

    @property
    def settings(self) -> GlobalSettings:
        return self._settings

    def file_path(self) -> "paths._PathLike":
        return paths.app_data_dir() / "settings.json"

    def load(self) -> GlobalSettings:
        with self._lock:
            try:
                data = json.loads(self.file_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            s = GlobalSettings()
            for key, value in data.items():
                if hasattr(s, key):
                    setattr(s, key, value)
            try:
                s.validate()
            except ValueError:
                s = GlobalSettings()
            self._settings = s
            return s

    def save(self) -> None:
        with self._lock:
            self._settings.validate()
            self.file_path().write_text(
                json.dumps(asdict(self._settings), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get(self) -> GlobalSettings:
        return self._settings

    def update(self, **kwargs) -> GlobalSettings:
        """更新若干字段并持久化；返回更新后的设置。"""
        with self._lock:
            changed = {}
            for key, value in kwargs.items():
                if not hasattr(self._settings, key):
                    raise KeyError(key)
                old = getattr(self._settings, key)
                if old != value:
                    setattr(self._settings, key, value)
                    changed[key] = value
            self._settings.validate()
            self.save()
        for key, value in changed.items():
            self._notify(key, value)
        return self._settings

    def add_listener(self, callback: Callable[[str, object], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self, key: str, value: object) -> None:
        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                pass

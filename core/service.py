"""服务编排：装配各模块，GUI 与 CLI（无界面后台运维）共用同一套业务逻辑。"""
from typing import Optional

from adb.adb_manager import AdbManager
from config.i18n import get_translator
from config.settings import SettingsManager
from core.instance_manager import InstanceManager
from core.qemu_manager import QemuManager
from core.resource_guard import ResourceGuard
from log.logger import get_logger
from mirror.image_manager import ImageManager


class StarARMService:
    """星模 ARM 原生安卓模拟器核心服务。"""

    def __init__(self) -> None:
        # 全局配置（主题 / 语言 / 资源阈值 / 路径）
        self.settings = SettingsManager()
        # 语言初始化：跟随系统，或用户已选语言（重启不重置）
        self.translator = get_translator()
        self.translator.set_language(self.settings.get().language)
        # 日志
        self.log = get_logger()
        # 模块装配
        self.images = ImageManager(self.settings)
        self.adb = AdbManager(self.settings)
        self.guard = ResourceGuard(self.settings)
        self.qemu = QemuManager(self.settings, self.images, self.adb, self.guard)
        self.instances = InstanceManager(self.settings, self.guard, self.qemu)
        self.log.system("log_app_start", version=self.version)

    @property
    def version(self) -> str:
        from config.constants import VERSION
        return VERSION

    def running_summary(self) -> dict:
        """运行中实例统计（GUI 状态栏 / CLI info 显示）。"""
        instances = self.instances.list_instances()
        running = [i for i in instances if i.state == "running"]
        return {
            "total": len(instances),
            "running": len(running),
            "cpu": sum(i.config.cpu_cores for i in running),
            "mem_gb": round(sum(i.config.memory_mb for i in running) / 1024.0, 1),
        }

    def apply_language_setting(self) -> None:
        """全局设置语言变化 -> 翻译器实时切换。"""
        self.translator.set_language(self.settings.get().language)

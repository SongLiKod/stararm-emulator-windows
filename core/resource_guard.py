"""资源超限保护：全局资源阈值，防止多开耗尽主机 CPU、内存。

阈值在全局设置中配置；0 表示按主机配置自动（留 2 核 / 一半内存余量）。
"""
import ctypes
import os
from dataclasses import dataclass
from typing import List, Tuple

from config.settings import GlobalSettings, SettingsManager


def host_cpu_cores() -> int:
    return os.cpu_count() or 4


def host_memory_gb() -> float:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            return 8.0
    else:
        try:
            import sysconfig
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return pages * page_size / (1024 ** 3)
        except Exception:
            return 8.0


@dataclass
class Thresholds:
    max_instances: int
    max_total_cpu_cores: int
    max_total_memory_gb: float


class ResourceGuard:
    """全局资源阈值守卫：创建与启动实例前校验。"""

    def __init__(self, settings: SettingsManager) -> None:
        self._settings = settings

    def thresholds(self) -> Thresholds:
        s: GlobalSettings = self._settings.get()
        cpu = host_cpu_cores()
        mem = host_memory_gb()
        max_cpu = s.max_total_cpu_cores if s.max_total_cpu_cores > 0 else max(1, cpu - 2)
        max_mem = s.max_total_memory_gb if s.max_total_memory_gb > 0 else round(max(1.0, mem / 2), 1)
        return Thresholds(
            max_instances=s.max_instances,
            max_total_cpu_cores=max_cpu,
            max_total_memory_gb=max_mem,
        )

    def check_create(self, used_instances: int) -> Tuple[bool, str]:
        """创建新实例校验（实例数量阈值）。"""
        t = self.thresholds()
        if used_instances >= t.max_instances:
            return False, "err_max_instances"
        return True, ""

    def check_start(
        self, candidate_cpu: int, candidate_mem_mb: int,
        running: List[Tuple[int, int]],
    ) -> Tuple[bool, str]:
        """启动实例校验：运行中实例 CPU/内存合计 + 新实例 不得超过全局阈值。"""
        t = self.thresholds()
        total_cpu = candidate_cpu + sum(c for c, _ in running)
        total_mem_gb = (candidate_mem_mb + sum(m for _, m in running)) / 1024.0
        if total_cpu > t.max_total_cpu_cores:
            return False, "err_max_total_cpu"
        if total_mem_gb > t.max_total_memory_gb:
            return False, "err_max_total_mem"
        if len(running) >= t.max_instances:
            return False, "err_max_instances"
        return True, ""

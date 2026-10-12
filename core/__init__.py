"""虚拟化核心层：QEMU调度、虚拟化核心、实例管理。"""
from core.instance import InstanceState, DeviceProfile, GpsConfig, BatteryConfig, InstanceConfig, Instance
from core.instance_manager import InstanceManager
from core.qemu_manager import QemuManager
from core.qemu_errors import classify_qemu_error
from core.virtualization import VirtualizationStatus, detect_virtualization
from core.resource_guard import ResourceGuard
from core.guest_agent import GuestAgentClient
from core.service import StarARMService

__all__ = [
    "InstanceState", "DeviceProfile", "GpsConfig", "BatteryConfig", "InstanceConfig", "Instance",
    "InstanceManager", "QemuManager", "classify_qemu_error",
    "VirtualizationStatus", "detect_virtualization",
    "ResourceGuard", "GuestAgentClient", "StarARMService",
]

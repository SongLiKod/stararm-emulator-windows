"""实例数据模型：状态、设备伪装、GPS、电池、资源配置。

实例数据独立存储、目录隔离（instances/<id>/），配置随实例目录持久化。
"""
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

from config.constants import DEFAULT_RESOLUTION, DEFAULT_DPI


class InstanceState:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

    ALL = (STOPPED, STARTING, RUNNING, STOPPING, ERROR)


@dataclass
class DeviceProfile:
    """全维度硬件模拟：自定义机型参数、序列号、Android ID、设备指纹、IMEI。"""
    brand: str = "STAR"
    model: str = "S1 Pro"
    manufacturer: str = "STAR"
    serial: str = ""
    imei: str = ""
    android_id: str = ""
    fingerprint: str = ""


@dataclass
class GpsConfig:
    """GPS 定位模拟：经纬度手动自定义。"""
    latitude: float = 39.9042
    longitude: float = 116.4074


@dataclass
class BatteryConfig:
    """电池状态模拟：电量 / 充电状态。"""
    level: int = 80
    charging: bool = True


@dataclass
class InstanceConfig:
    """单实例独立资源配置（CPU / 内存 / 磁盘）与显示、网络、ADB 端口。"""
    cpu_cores: int = 4
    memory_mb: int = 4096
    disk_gb: int = 32
    resolution: str = DEFAULT_RESOLUTION
    dpi: int = DEFAULT_DPI
    network_mode: str = "nat"          # nat | bridge
    bridge_adapter: str = ""           # 桥接网卡名称（TAP）
    graphics: str = "virgl-vulkan"     # virgl-vulkan | virgl | software
    fullscreen: bool = False           # 打开显示窗口时是否全屏
    adb_port: int = 0                  # 0 = 启动时分配
    vnc_display: int = -1              # -1 = 启动时分配（端口 = 5900 + display）
    agent_port: int = 0                # 0 = 启动时分配
    device: DeviceProfile = field(default_factory=DeviceProfile)
    gps: GpsConfig = field(default_factory=GpsConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)


@dataclass
class Instance:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    image_id: str = ""
    state: str = InstanceState.STOPPED
    created_at: float = field(default_factory=time.time)
    config: InstanceConfig = field(default_factory=InstanceConfig)
    last_error: str = ""
    last_error_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "image_id": self.image_id,
            "state": self.state,
            "created_at": self.created_at,
            "config": asdict(self.config),
            "last_error": self.last_error,
            "last_error_detail": self.last_error_detail,
        }

    @staticmethod
    def from_dict(data: dict) -> "Instance":
        cfg_data = dict(data.get("config") or {})
        device = DeviceProfile(**{k: v for k, v in (cfg_data.pop("device", {}) or {}).items()
                                  if k in DeviceProfile.__dataclass_fields__})
        gps = GpsConfig(**{k: v for k, v in (cfg_data.pop("gps", {}) or {}).items()
                           if k in GpsConfig.__dataclass_fields__})
        battery = BatteryConfig(**{k: v for k, v in (cfg_data.pop("battery", {}) or {}).items()
                                   if k in BatteryConfig.__dataclass_fields__})
        for k in list(cfg_data.keys()):
            if k not in InstanceConfig.__dataclass_fields__:
                cfg_data.pop(k)
        cfg = InstanceConfig(device=device, gps=gps, battery=battery, **cfg_data)
        inst = Instance(
            id=data.get("id") or uuid.uuid4().hex[:12],
            name=data.get("name", ""),
            image_id=data.get("image_id", ""),
            state=data.get("state", InstanceState.STOPPED),
            created_at=float(data.get("created_at", time.time())),
            config=cfg,
            last_error=data.get("last_error", ""),
            last_error_detail=data.get("last_error_detail", ""),
        )
        return inst

    @property
    def memory_gb_text(self) -> str:
        return f"{self.config.memory_mb / 1024:.1f}"

    @property
    def resolution_text(self) -> str:
        return self.config.resolution

    @property
    def vnc_port(self) -> int:
        return 5900 + self.config.vnc_display if self.config.vnc_display >= 0 else 0

    @property
    def data_dir(self):
        from config import paths
        return paths.instance_dir(self.id)

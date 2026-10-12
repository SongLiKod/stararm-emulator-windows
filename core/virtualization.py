"""主机虚拟化检测：VT-x / AMD-V 固件开关 + Windows 虚拟化加速（WHPX）可用性。

- 开启：优先使用 WHPX（Windows Hypervisor Platform，KVM-like Windows 虚拟化加速）
- 未开启：自动降级为 TCG 软件仿真，并给出中文教程引导（见 GUI 虚拟化教程对话框）
"""
import ctypes
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class VirtualizationStatus:
    firmware_enabled: Optional[bool]   # VT-x/AMD-V 固件开关（None=未知）
    whpx_available: bool               # Windows 虚拟化加速（WHPX）可用
    method: str                        # "whpx" | "tcg"
    accelerated: bool                  # 是否硬件加速模式

    @property
    def firmware_disabled(self) -> bool:
        return self.firmware_enabled is False

    @property
    def firmware_unknown(self) -> bool:
        return self.firmware_enabled is None


def _query_firmware_vt() -> Optional[bool]:
    """通过 Win32_Processor.VirtualizationFirmwareEnabled 查询 VT-x/AMD-V 固件开关。"""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled",
            ],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = (out.stdout or "").strip().lower()
        if value in ("true", "false"):
            return value == "true"
    except Exception:
        pass
    return None


def _whpx_available() -> bool:
    """检测 Windows Hypervisor Platform 加速库是否可用。"""
    try:
        ctypes.WinDLL("whpx.dll")
        return True
    except Exception:
        return False


def detect_virtualization() -> VirtualizationStatus:
    """自动检测主机 VT-x/AMD-V 与 WHPX 状态。"""
    firmware = _query_firmware_vt()
    whpx = _whpx_available()
    accelerated = whpx and (firmware is not False)
    return VirtualizationStatus(
        firmware_enabled=firmware,
        whpx_available=whpx,
        method="whpx" if accelerated else "tcg",
        accelerated=accelerated,
    )

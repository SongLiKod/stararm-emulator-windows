"""主机虚拟化检测：VT-x / AMD-V 固件开关 + Windows 虚拟化加速（WHPX）可用性。

结论分四类（reason），避免"BIOS 已开启却提示未开启"的误报：

- ``ok``       硬件加速可用（WHPX），使用 ``-accel whpx``
- ``firmware`` BIOS/UEFI 中 VT-x / AMD-V 未开启 → 中文 BIOS 图文教程
- ``whpx``     BIOS 虚拟化已开启，但 Windows 的「虚拟机监控程序平台」
               （Hypervisor Platform / WHPX）功能未启用 → 一键启用 Windows 功能
- ``unknown``  检测通道全部失败（无法判定）

关键坑位：当 Hyper-V / WSL2 / Docker 等虚拟机监控程序已在运行时，
``Win32_Processor.VirtualizationFirmwareEnabled`` 常返回 ``False``
（固件虚拟化资源已被占用），此时 VT-x/AMD-V 实际可用，
必须用 ``Win32_ComputerSystem.HypervisorPresent`` 兜底，否则会误报"未开启"。
"""
import ctypes
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional


REASON_OK = "ok"
REASON_FIRMWARE = "firmware"
REASON_WHPX = "whpx"
REASON_UNKNOWN = "unknown"

# 单次 PowerShell 探测三路状态（WMI 需要 PowerShell；Win32_OptionalFeature 无需管理员）
_PROBE_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$r=@{};"
    "$p=Get-CimInstance Win32_Processor | Select-Object -First 1;"
    "if($p -and $null -ne $p.VirtualizationFirmwareEnabled)"
    "{$r.firmware=[bool]$p.VirtualizationFirmwareEnabled};"
    "$c=Get-CimInstance Win32_ComputerSystem;"
    "if($c -and $null -ne $c.HypervisorPresent)"
    "{$r.hypervisor=[bool]$c.HypervisorPresent};"
    "$f=Get-CimInstance Win32_OptionalFeature -Filter \"Name='HypervisorPlatform'\";"
    "if($f){$r.whpx_feature=[bool]($f.InstallState -eq 1)};"
    "ConvertTo-Json -InputObject $r -Compress"
)


@dataclass
class VirtualizationStatus:
    firmware_enabled: Optional[bool]   # VT-x/AMD-V 固件开关（None=未知）
    whpx_available: bool               # Windows 虚拟化加速（WHPX）可用
    method: str                        # "whpx" | "tcg"
    accelerated: bool                  # 是否硬件加速模式
    hypervisor_present: Optional[bool] = None  # 系统已有虚拟机监控程序在运行
    whpx_feature: Optional[bool] = None        # 「虚拟机监控程序平台」功能是否启用
    reason: str = REASON_UNKNOWN               # ok | firmware | whpx | unknown

    @property
    def firmware_disabled(self) -> bool:
        """固件虚拟化明确关闭（虚拟机监控程序已运行时不算关闭）。"""
        return self.reason == REASON_FIRMWARE

    @property
    def firmware_unknown(self) -> bool:
        return self.firmware_enabled is None and self.hypervisor_present is None

    @property
    def needs_whpx(self) -> bool:
        """BIOS 虚拟化没问题，只是 Windows 虚拟机监控程序平台功能未启用。"""
        return self.reason == REASON_WHPX


def parse_probe(text: str) -> Dict[str, Optional[bool]]:
    """解析 PowerShell 探测结果 JSON -> {firmware, hypervisor, whpx_feature}。"""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Optional[bool]] = {}
    for key in ("firmware", "hypervisor", "whpx_feature"):
        value = data.get(key)
        if isinstance(value, bool):
            out[key] = value
    return out


def _run_probe() -> Dict[str, Optional[bool]]:
    if os.name != "nt":
        return {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PROBE_SCRIPT],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_probe(out.stdout or "")


def whpx_dll_available() -> bool:
    """WHPX 动态库是否可用（「虚拟机监控程序平台」功能安装后才有该库）。"""
    if os.name != "nt":
        return False
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    for path in (os.path.join(root, "System32", "whpx.dll"),):
        if os.path.isfile(path):
            return True
    try:
        ctypes.WinDLL("whpx.dll")
        return True
    except OSError:
        return False
    except Exception:  # pragma: no cover - 非 Windows / 加载器异常
        return False


def detect_virtualization() -> VirtualizationStatus:
    """自动检测主机 VT-x/AMD-V 与 WHPX 状态（幂等，由调用方缓存）。"""
    probe = _run_probe()
    firmware = probe.get("firmware")
    hypervisor = probe.get("hypervisor")
    whpx_feature = probe.get("whpx_feature")
    whpx = whpx_dll_available() or whpx_feature is True

    firmware_disabled = firmware is False and hypervisor is not True
    probed = bool(probe)

    if firmware_disabled:
        reason = REASON_FIRMWARE
    elif whpx:
        reason = REASON_OK
    elif probed:
        reason = REASON_WHPX
    else:
        reason = REASON_UNKNOWN

    accelerated = reason == REASON_OK
    return VirtualizationStatus(
        firmware_enabled=firmware,
        whpx_available=whpx,
        method="whpx" if accelerated else "tcg",
        accelerated=accelerated,
        hypervisor_present=hypervisor,
        whpx_feature=whpx_feature,
        reason=reason,
    )

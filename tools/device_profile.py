"""全维度硬件模拟：机型参数、序列号、IMEI、Android ID、设备指纹、GPS、电池。

应用通道：
- 属性：客户代理 props.set（主，内置镜像 root 代理） + adb setprop（回退，best-effort）
- 序列号：QEMU 启动参数 androidboot.serialno=<serial>（每次开机生效，见 qemu_manager）
- Android ID：adb settings put secure（root）
- GPS：客户代理 gps 命令；电池：adb dumpsys battery set（内置 userdebug 镜像）
- 弱化 QEMU 模拟器特征：抹除 ro.kernel.qemu / ro.boot.qemu 等通用模拟器标识
"""
import random
import string
from typing import Dict, List, Tuple

from adb.adb_manager import AdbManager
from core.guest_agent import GuestAgentClient
from core.instance import DeviceProfile, InstanceConfig

COMMON_BRANDS: Dict[str, List[str]] = {
    "Samsung": ["Galaxy S24", "Galaxy S23", "Galaxy Note20"],
    "Xiaomi": ["Xiaomi 14", "Redmi K70", "Xiaomi 13"],
    "HUAWEI": ["Mate 60", "P60", "nova 12"],
    "OPPO": ["Find X7", "Reno11"],
    "vivo": ["X100", "S19"],
    "OnePlus": ["Ace 3", "12"],
    "Google": ["Pixel 8", "Pixel 9"],
    "Honor": ["Magic6", "90 GT"],
}

# 弱化模拟器特征：抹除通用模拟器设备标识
ANTI_EMULATOR_PROPS: Dict[str, str] = {
    "ro.kernel.qemu": "0",
    "ro.boot.qemu": "0",
    "ro.hardware": "stararm",
    "ro.boot.hardware": "stararm",
}


def luhn_checksum_digit(digits: str) -> str:
    """标准 Luhn 校验位（IMEI 第 15 位）。

    digits 为前 14 位载荷；校验位使完整 15 位通过 Luhn 校验
    （完整号码从右起第 2 位开始加倍，即载荷反转后偶数下标加倍）。
    """
    total = 0
    for index, ch in enumerate(reversed(digits)):
        d = int(ch)
        if index % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def generate_imei() -> str:
    digits = "".join(random.choices(string.digits, k=14))
    return digits + luhn_checksum_digit(digits)


def generate_serial(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_android_id() -> str:
    return "".join(random.choices("0123456789abcdef", k=16))


def build_fingerprint(brand: str, model: str, android_version: int, serial: str) -> str:
    return (
        f"{brand}/{model}/{model}:{android_version}/"
        f"STARM.{android_version}.{serial}/user/release-keys"
    )


def generate_profile() -> DeviceProfile:
    """随机生成一套设备伪装参数。"""
    brand = random.choice(list(COMMON_BRANDS.keys()))
    model = random.choice(COMMON_BRANDS[brand])
    serial = generate_serial()
    return DeviceProfile(
        brand=brand,
        model=model,
        manufacturer=brand,
        serial=serial,
        imei=generate_imei(),
        android_id=generate_android_id(),
        fingerprint=build_fingerprint(brand, model, 13, serial),
    )


def build_props(device: DeviceProfile) -> Dict[str, str]:
    props = {
        "ro.product.brand": device.brand,
        "ro.product.manufacturer": device.manufacturer,
        "ro.product.model": device.model,
        "ro.product.device": device.model.replace(" ", ""),
        "ro.product.name": device.model.replace(" ", ""),
        "ro.build.fingerprint": device.fingerprint,
        "ro.serialno": device.serial,
    }
    props.update(ANTI_EMULATOR_PROPS)
    return props


def apply_profile(
    adb: AdbManager,
    agent: GuestAgentClient,
    config: InstanceConfig,
    android_version: int,
) -> List[Tuple[str, bool]]:
    """开机后应用硬件模拟参数，返回 [(项目, 是否成功)]。"""
    report: List[Tuple[str, bool]] = []
    device = config.device
    port = config.adb_port
    if not device.serial:
        device.serial = generate_serial()
    if not device.android_id:
        device.android_id = generate_android_id()
    if not device.fingerprint:
        device.fingerprint = build_fingerprint(
            device.brand, device.model, android_version, device.serial)

    # 1) 机型 / 序列号 / 指纹 / 反模拟器标识属性
    props = build_props(device)
    agent_ok = agent.set_props(props) if agent else False
    report.append(("props", agent_ok))
    for key, value in props.items():
        if not agent_ok:
            try:
                adb.setprop(port, key, value)
            except Exception:
                pass

    # 2) Android ID
    try:
        ok_id = adb.settings_put_secure(port, "android_id", device.android_id)
    except Exception:
        ok_id = False
    report.append(("android_id", ok_id))

    # 3) IMEI（客户代理通道）
    imei_ok = False
    if agent and device.imei:
        imei_ok = agent.set_imei(device.imei)
    report.append(("imei", imei_ok))

    # 4) GPS 定位模拟（客户代理通道）
    try:
        gps_ok = agent.set_gps(config.gps.latitude, config.gps.longitude) if agent else False
    except Exception:
        gps_ok = False
    report.append(("gps", gps_ok))

    # 5) 电池状态模拟
    try:
        battery_ok = adb.battery_set(port, config.battery.level, config.battery.charging)
    except Exception:
        battery_ok = False
    report.append(("battery", battery_ok))
    return report

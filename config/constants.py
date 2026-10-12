"""固定落地参数与全局常量。"""
from typing import Dict, List, Tuple

APP_NAME_ZH = "星模ARM原生安卓模拟器"
APP_NAME_EN = "StarARM Emulator"
VERSION = "1.0.0"

# 分辨率预设：240P - 4K（此外支持自定义宽高）
RESOLUTION_PRESETS: Dict[str, str] = {
    "240P": "426x240",
    "360P": "640x360",
    "480P": "854x480",
    "720P": "1280x720",
    "1080P": "1920x1080",
    "2K": "2560x1440",
    "4K": "3840x2160",
}
DEFAULT_RESOLUTION = "1280x720"
DEFAULT_DPI = 320
DPI_MIN = 120
DPI_MAX = 640

# 网络模式：NAT（默认）/ 桥接
NETWORK_MODES: List[str] = ["nat", "bridge"]
# 图形加速：VirGL+Vulkan / VirGL(OpenGL ES) / 软件渲染
GRAPHICS_MODES: List[str] = ["virgl-vulkan", "virgl", "software"]

# 支持的安卓镜像版本：11 - 15
ANDROID_VERSIONS: List[int] = [11, 12, 13, 14, 15]

# 端口规划
ADB_PORT_RANGE: Tuple[int, int] = (5555, 6000)
VNC_DISPLAY_RANGE: Tuple[int, int] = (0, 200)  # VNC 端口 = 5900 + display
AGENT_PORT_RANGE: Tuple[int, int] = (20000, 60000)

# 客户代理通道 virtio-serial 端口名（内置 AOSP 镜像内含 stararm-agent 守护进程）
GUEST_AGENT_PORT_NAME = "stararm.agent"

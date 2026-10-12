"""独立 ADB 端口分配：单实例独立绑定唯一 ADB 端口，无端口冲突。

- ADB 端口：5555-6000（TCP 直通，外部工具可 adb connect 127.0.0.1:<port>）
- VNC 显示端口：5900 + display（display 0-200，显示窗口渲染用）
- 客户代理端口：20000-60000
"""
import socket
from typing import Iterable, Optional, Set, Tuple

from config.constants import ADB_PORT_RANGE, VNC_DISPLAY_RANGE, AGENT_PORT_RANGE


def _is_free(port: int) -> bool:
    """探测端口是否真正可用。

    不设置 SO_REUSEADDR（Windows 下 REUSEADDR 允许覆盖已监听端口，
    会把被 adb/qemu 等占用的端口误判为空闲导致端口冲突）。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def find_free_port(start: int, end: int, exclude: Optional[Set[int]] = None) -> Optional[int]:
    """在 [start, end] 内查找未被占用且不在 exclude 中的端口。"""
    exclude = exclude or set()
    for port in range(start, end + 1):
        if port in exclude:
            continue
        if _is_free(port):
            return port
    return None


def find_free_display(exclude: Optional[Set[int]] = None) -> Optional[int]:
    """查找可用 VNC display 编号（端口 = 5900 + display）。"""
    exclude = exclude or set()
    for display in range(VNC_DISPLAY_RANGE[0], VNC_DISPLAY_RANGE[1] + 1):
        if display in exclude:
            continue
        if _is_free(5900 + display):
            return display
    return None


def allocate_ports(
    used_adb: Iterable[int] = (),
    used_displays: Iterable[int] = (),
    used_agent: Iterable[int] = (),
) -> Tuple[int, int, int]:
    """为实例分配 (adb_port, vnc_display, agent_port)；分配失败抛出 RuntimeError。"""
    adb = find_free_port(ADB_PORT_RANGE[0], ADB_PORT_RANGE[1], set(used_adb))
    display = find_free_display(set(used_displays))
    agent = find_free_port(AGENT_PORT_RANGE[0], AGENT_PORT_RANGE[1], set(used_agent))
    if adb is None or display is None or agent is None:
        raise RuntimeError("err_no_free_port")
    return adb, display, agent

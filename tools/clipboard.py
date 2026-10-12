"""宿主机-虚拟机剪贴板双向同步。

主通道：客户代理 clipboard.set / clipboard.get（virtio-serial）。
回退通道（代理不可用）：
- 宿主 -> 虚拟机：adb input text（内容输入，非严格剪贴板，best-effort）
- 虚拟机 -> 宿主：解析 adb dumpsys clipboard 文本
"""
from adb.adb_manager import AdbManager
from core.guest_agent import GuestAgentClient
from log.logger import get_logger


def sync_to_guest(text: str, adb: AdbManager, port: int,
                  agent: GuestAgentClient = None) -> bool:
    """宿主机剪贴板 -> 虚拟机。"""
    if agent is not None:
        try:
            if agent.set_clipboard(text):
                get_logger().run("log_clipboard_to_guest", channel="agent")
                return True
        except Exception:
            pass
    try:
        ok = adb.input_clipboard_text(port, text)
        if ok:
            get_logger().run("log_clipboard_to_guest", channel="adb")
        return ok
    except Exception:
        return False


def sync_from_guest(adb: AdbManager, port: int,
                    agent: GuestAgentClient = None) -> str:
    """虚拟机剪贴板 -> 宿主机，返回文本（失败返回空串）。"""
    if agent is not None:
        try:
            text = agent.get_clipboard()
            if text is not None:
                get_logger().run("log_clipboard_to_host", channel="agent")
                return text
        except Exception:
            pass
    try:
        text = adb.dumpsys_clipboard_text(port)
        if text:
            get_logger().run("log_clipboard_to_host", channel="adb")
        return text
    except Exception:
        return ""

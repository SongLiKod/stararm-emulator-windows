"""客户代理通道（virtio-serial）。

QEMU 侧：-chardev socket,id=ga0,host=127.0.0.1,port=<agent_port>,server=on,wait=off
        -device virtio-serial-device -device virtserialport,chardev=ga0,name=stararm.agent

内置 AOSP ARM64 镜像内含 stararm-agent 守护进程，监听该串口，支持 JSON 行协议：
  请求：{"cmd": "gps",        "lat": 39.9042, "lng": 116.4074}
  请求：{"cmd": "clipboard.set", "text": "..."}
  请求：{"cmd": "clipboard.get"}
  请求：{"cmd": "imei.set",   "imei": "..."}
  请求：{"cmd": "props.set",  "props": {"ro.product.model": "..."}}
  响应：{"ok": true, ...}

通道不可用时，宿主自动回退 ADB 方式（见 tools/device_profile.py、tools/clipboard.py）。
"""
import json
import socket
from typing import Optional


class GuestAgentClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def _transact(self, request: dict) -> Optional[dict]:
        if not self.port:
            return None
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
                data = b""
                while b"\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            if not data:
                return None
            line = data.split(b"\n")[0].decode("utf-8", errors="replace")
            return json.loads(line)
        except (OSError, ValueError):
            return None

    def set_gps(self, latitude: float, longitude: float) -> bool:
        resp = self._transact({"cmd": "gps", "lat": latitude, "lng": longitude})
        return bool(resp and resp.get("ok"))

    def set_clipboard(self, text: str) -> bool:
        resp = self._transact({"cmd": "clipboard.set", "text": text})
        return bool(resp and resp.get("ok"))

    def get_clipboard(self) -> Optional[str]:
        resp = self._transact({"cmd": "clipboard.get"})
        if resp and resp.get("ok"):
            return resp.get("text")
        return None

    def set_imei(self, imei: str) -> bool:
        resp = self._transact({"cmd": "imei.set", "imei": imei})
        return bool(resp and resp.get("ok"))

    def set_props(self, props: dict) -> bool:
        resp = self._transact({"cmd": "props.set", "props": props})
        return bool(resp and resp.get("ok"))

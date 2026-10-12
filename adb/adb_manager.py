"""ADB 管理器：基于原生 adb 二进制，完全兼容标准 ADB 协议。

- 每实例独立 ADB 端口（adb connect 127.0.0.1:<port>）
- 支持第三方工具 / 脚本直接连接调试
- APK 安装、文件推拉、shell、截图、录屏、分辨率 /DPI、属性 / 设置、电池 / 剪贴板等
"""
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import SettingsManager
from log.logger import get_logger

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


class AdbError(RuntimeError):
    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(detail)
        self.key = key
        self.detail = detail


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


class AdbManager:
    """ADB 封装。所有命令走原生 adb，保证协议 100% 兼容。"""

    def __init__(self, settings: SettingsManager) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._binary: Optional[str] = None

    # ------------------------------------------------------------- locate
    def locate_adb(self) -> str:
        with self._lock:
            if self._binary:
                return self._binary
            candidates: List[Path] = []
            s = self._settings.get()
            if s.adb_path:
                candidates.append(Path(s.adb_path))
            # 部署包内置 adb（<安装目录>/adb-runtime/adb.exe，绿色免配置）
            import sys
            if getattr(sys, "frozen", False):
                candidates.append(Path(sys.executable).resolve().parent / "adb-runtime" / "adb.exe")
            else:
                candidates.append(Path(__file__).resolve().parent.parent / "adb-runtime" / "adb.exe")
            if os.name == "nt":
                sdk = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
                candidates.append(sdk)
            which = shutil.which("adb")
            if which:
                candidates.append(Path(which))
            for c in candidates:
                if c.is_file():
                    self._binary = str(c)
                    return self._binary
            self._binary = "adb"
            return self._binary

    def adb_available(self) -> bool:
        binary = self.locate_adb()
        if binary != "adb" or shutil.which("adb"):
            try:
                out = self._run(["version"], timeout=10).stdout or ""
                return "Android Debug Bridge" in out or "adb" in out.lower()
            except Exception:
                return False
        return False

    # ------------------------------------------------------------- runner
    def _run(self, args: List[str], timeout: float = 30) -> subprocess.CompletedProcess:
        cmd = [self.locate_adb()] + args
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )

    def _run_bytes(self, args: List[str], timeout: float = 60) -> bytes:
        cmd = [self.locate_adb()] + args
        return subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        ).stdout

    def start_server(self) -> None:
        try:
            self._run(["start-server"], timeout=15)
        except Exception:
            pass

    # ------------------------------------------------------------- device
    def connect(self, port: int) -> bool:
        try:
            out = self._run(["connect", f"127.0.0.1:{port}"], timeout=15)
            return f"127.0.0.1:{port}" in (out.stdout or "")
        except Exception:
            return False

    def disconnect(self, port: int) -> None:
        try:
            self._run(["disconnect", f"127.0.0.1:{port}"], timeout=15)
        except Exception:
            pass

    def is_connected(self, port: int) -> bool:
        try:
            out = self._run(["devices"], timeout=15)
            return f"127.0.0.1:{port}\tdevice" in (out.stdout or "")
        except Exception:
            return False

    def devices(self) -> Dict[str, str]:
        try:
            out = self._run(["devices"], timeout=15)
            result: Dict[str, str] = {}
            for line in (out.stdout or "").splitlines():
                parts = line.split("\t")
                if len(parts) == 2 and parts[1] in ("device", "offline", "unauthorized"):
                    result[parts[0]] = parts[1]
            return result
        except Exception:
            return {}

    def shell(self, port: int, command: str, timeout: float = 30) -> str:
        serial = f"127.0.0.1:{port}"
        out = self._run(["-s", serial, "shell", command], timeout=timeout)
        if out.returncode != 0 and out.stderr and "no devices" in (out.stderr or "").lower():
            raise AdbError("err_adb_not_connected", out.stderr or "")
        return (out.stdout or "").strip()

    def shell_ok(self, port: int, command: str, timeout: float = 30) -> bool:
        try:
            self.shell(port, command, timeout=timeout)
            return True
        except Exception:
            return False

    def adb_root(self, port: int) -> bool:
        """内置 AOSP userdebug 镜像支持 adb root（设备伪装 / 属性修改用）。"""
        try:
            serial = f"127.0.0.1:{port}"
            self._run(["-s", serial, "root"], timeout=15)
            time.sleep(0.5)
            self.connect(port)
            return True
        except Exception:
            return False

    def wait_booted(self, port: int, timeout: float = 300, poll: float = 3.0,
                    progress=None) -> bool:
        """等待设备开机完成（sys.boot_completed=1）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.connect(port)
                out = self.shell(port, "getprop sys.boot_completed", timeout=15)
                if out.strip().endswith("1"):
                    return True
            except Exception:
                pass
            if progress:
                try:
                    progress(timeout - (deadline - time.time()))
                except Exception:
                    pass
            time.sleep(poll)
        return False

    # ------------------------------------------------------------- install
    def install(self, port: int, apk_path: str, timeout: float = 600) -> str:
        serial = f"127.0.0.1:{port}"
        out = self._run(["-s", serial, "install", "-r", apk_path], timeout=timeout)
        text = (out.stdout or "") + (out.stderr or "")
        if "Success" in text:
            return "success"
        if "INSTALL_FAILED_NO_MATCHING_ABIS" in text:
            raise AdbError("err_abi_mismatch", text)
        raise AdbError("err_install_failed", text)

    # ------------------------------------------------------------- files
    def push(self, port: int, local: str, remote: str, timeout: float = 600) -> bool:
        serial = f"127.0.0.1:{port}"
        out = self._run(["-s", serial, "push", local, remote], timeout=timeout)
        return "file pushed" in (out.stdout or "").lower() or out.returncode == 0

    def pull(self, port: int, remote: str, local: str, timeout: float = 600) -> bool:
        serial = f"127.0.0.1:{port}"
        out = self._run(["-s", serial, "pull", remote, local], timeout=timeout)
        return out.returncode == 0 and Path(local).exists()

    def list_guest_files(self, port: int, guest_dir: str) -> List[Tuple[str, int, int]]:
        """列出模拟器目录内文件：[(路径, mtime, size)]（toybox stat -c 输出）。"""
        cmd = f"find {_quote(guest_dir)} -type f -exec stat -c '%Y %s %n' {{}} +"
        try:
            out = self.shell(port, cmd, timeout=60)
        except Exception:
            return []
        files: List[Tuple[str, int, int]] = []
        for line in (out or "").splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) == 3 and parts[0].isdigit():
                files.append((parts[2], int(parts[0]), int(parts[1])))
        return files

    # ------------------------------------------------------------- input
    def input_tap(self, port: int, x: int, y: int) -> None:
        self.shell(port, f"input tap {int(x)} {int(y)}")

    def input_swipe(self, port: int, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(port, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def input_key(self, port: int, keycode: int) -> None:
        self.shell(port, f"input keyevent {int(keycode)}")

    def input_text(self, port: int, text: str) -> None:
        escaped = str(text).replace(" ", "%s").replace('"', '\\"')
        self.shell(port, f'input text "{escaped}"')

    # ------------------------------------------------------------- display
    def wm_size(self, port: int, width: int, height: int) -> None:
        self.shell(port, f"wm size {int(width)}x{int(height)}")

    def wm_density(self, port: int, dpi: int) -> None:
        self.shell(port, f"wm density {int(dpi)}")

    def screencap_png(self, port: int, timeout: float = 30) -> bytes:
        serial = f"127.0.0.1:{port}"
        return self._run_bytes(
            ["-s", serial, "exec-out", "screencap -p"], timeout=timeout,
        )

    # ------------------------------------------------------------- power / battery
    def battery_set(self, port: int, level: int, charging: bool) -> bool:
        """电池状态模拟（内置 userdebug 镜像支持 dumpsys battery set）。"""
        try:
            self.shell(port, f"dumpsys battery set level {max(0, min(100, int(level)))}")
            status = 2 if charging else 3  # 2=充电中 3=放电
            self.shell(port, f"dumpsys battery set status {status}")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- settings / props
    def settings_put_secure(self, port: int, key: str, value: str) -> bool:
        return self.shell_ok(port, f"settings put secure {_quote(key)} {_quote(value)}")

    def setprop(self, port: int, key: str, value: str) -> bool:
        return self.shell_ok(port, f"setprop {_quote(key)} {_quote(value)}")

    # ------------------------------------------------------------- recording
    def screenrecord_start(self, port: int, remote_path: str, time_limit_s: int = 180):
        """启动模拟器内录屏（后台线程执行 adb shell screenrecord）。"""
        serial = f"127.0.0.1:{port}"
        cmd = [self.locate_adb(), "-s", serial, "shell",
               "screenrecord", "--time-limit", str(int(time_limit_s)), remote_path]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc

    def screenrecord_stop(self, port: int) -> None:
        try:
            self.shell(port, "pkill -2 screenrecord", timeout=15)
        except Exception:
            pass

    def poweroff(self, port: int) -> None:
        try:
            self.shell(port, "reboot -p", timeout=30)
        except Exception:
            pass

    # ------------------------------------------------------------- clipboard
    def dumpsys_clipboard_text(self, port: int) -> str:
        """剪贴板回退方案：解析 dumpsys clipboard 文本（客户代理优先）。"""
        try:
            out = self.shell(port, "dumpsys clipboard", timeout=15)
        except Exception:
            return ""
        match = re.search(r"TextCell\[\s*text=([^\n,]*)", out)
        if not match:
            match = re.search(r"[Tt]ext=([^\n,]*)", out)
        return match.group(1).strip() if match else ""

    def input_clipboard_text(self, port: int, text: str) -> bool:
        """剪贴板回退方案：通过 input text 输入文本（客户代理优先）。"""
        try:
            self.input_text(port, text)
            return True
        except Exception:
            return False

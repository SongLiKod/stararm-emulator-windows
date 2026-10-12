"""测试公共夹具：独立 STARARM_HOME、共享假 ADB。"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def stararm_home(tmp_path, monkeypatch):
    """每个测试使用独立的用户数据目录（不污染真实环境）。"""
    home = tmp_path / "stararm-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STARARM_HOME", str(home))
    import config.i18n as i18n_mod
    i18n_mod._translator = None
    import log.logger as logger_mod
    logger_mod._logger = None
    return home


class FakeAdb:
    """记录调用的 ADB 假实现（供工具层测试）。"""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, ...]] = []
        self.shell_outputs: Dict[str, str] = {}
        self.pushed: List[Tuple[str, str]] = []
        self.pulled: List[Tuple[str, str]] = []
        self._guest_files: Dict[str, List[Tuple[str, int, int]]] = {}

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, *args))

    # ---- AdbManager 接口子集 ----
    def connect(self, port: int) -> bool:
        self._record("connect", port)
        return True

    def is_connected(self, port: int) -> bool:
        return True

    def shell(self, port: int, command: str, timeout: float = 30) -> str:
        self._record("shell", port, command)
        for prefix, output in self.shell_outputs.items():
            if command.startswith(prefix):
                return output
        return ""

    def shell_ok(self, port: int, command: str, timeout: float = 30) -> bool:
        self.shell(port, command, timeout)
        return True

    def adb_root(self, port: int) -> bool:
        self._record("adb_root", port)
        return True

    def input_tap(self, port: int, x: int, y: int) -> None:
        self._record("input_tap", port, x, y)

    def input_swipe(self, port: int, x1: int, y1: int, x2: int, y2: int,
                    duration_ms: int = 300) -> None:
        self._record("input_swipe", port, x1, y1, x2, y2, duration_ms)

    def input_key(self, port: int, keycode: int) -> None:
        self._record("input_key", port, keycode)

    def input_text(self, port: int, text: str) -> None:
        self._record("input_text", port, text)

    def wm_size(self, port: int, w: int, h: int) -> None:
        self._record("wm_size", port, w, h)

    def wm_density(self, port: int, dpi: int) -> None:
        self._record("wm_density", port, dpi)

    def settings_put_secure(self, port: int, key: str, value: str) -> bool:
        self._record("settings_put_secure", port, key, value)
        return True

    def setprop(self, port: int, key: str, value: str) -> bool:
        self._record("setprop", port, key, value)
        return True

    def battery_set(self, port: int, level: int, charging: bool) -> bool:
        self._record("battery_set", port, level, charging)
        return True

    def push(self, port: int, local: str, remote: str, timeout: float = 600) -> bool:
        self._record("push", port, local, remote)
        self.pushed.append((local, remote))
        return True

    def pull(self, port: int, remote: str, local: str, timeout: float = 600) -> bool:
        self._record("pull", port, remote, local)
        self.pulled.append((remote, local))
        dest = Path(local)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"guest:{remote}", encoding="utf-8")
        return True

    def list_guest_files(self, port: int, guest_dir: str) -> List[Tuple[str, int, int]]:
        self._record("list_guest_files", port, guest_dir)
        return self._guest_files.get(guest_dir, [])

    def set_guest_files(self, guest_dir: str, files: List[Tuple[str, int, int]]) -> None:
        self._guest_files[guest_dir] = files

    def dumpsys_clipboard_text(self, port: int) -> str:
        return self.shell_outputs.get("dumpsys clipboard", "")


@pytest.fixture
def fake_adb() -> FakeAdb:
    return FakeAdb()

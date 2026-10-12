"""录屏工具：ADB screenrecord，文件自动保存至本地录屏目录。"""
import threading
import time
from pathlib import Path
from typing import Optional

from adb.adb_manager import AdbManager
from config import paths
from log.logger import get_logger

MAX_RECORD_SECONDS = 180


class ScreenRecorder:
    """单实例录屏器：开始 -> （可选提前停止）-> 自动拉取保存。"""

    def __init__(self, adb: AdbManager) -> None:
        self._adb = adb
        self._lock = threading.Lock()
        self._proc = None
        self._port = 0
        self._remote = ""
        self._name = ""
        self._thread: Optional[threading.Thread] = None

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._proc is not None

    def start(self, port: int, instance_name: str = "", seconds: int = MAX_RECORD_SECONDS) -> None:
        with self._lock:
            if self._proc is not None:
                raise RuntimeError("err_already_recording")
            self._port = port
            self._name = instance_name
            self._remote = f"/sdcard/stararm-{int(time.time())}.mp4"
            seconds = max(1, min(MAX_RECORD_SECONDS, int(seconds)))
            self._proc = self._adb.screenrecord_start(port, self._remote, seconds)
        get_logger().run("log_record_started", id=instance_name)

    def stop(self, out_dir: Optional[Path] = None) -> Path:
        """停止录屏并保存文件，返回文件路径。"""
        with self._lock:
            proc = self._proc
            remote = self._remote
            port = self._port
            name = self._name
            if proc is None:
                raise RuntimeError("err_not_recording")
            self._proc = None
        try:
            self._adb.screenrecord_stop(port)
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        out_dir = Path(out_dir) if out_dir else paths.recordings_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        safe = name.replace(" ", "_") if name else "instance"
        local = out_dir / f"stararm-{safe}-{ts}.mp4"
        ok = self._adb.pull(port, remote, str(local))
        try:
            self._adb.shell(port, f"rm -f {remote}")
        except Exception:
            pass
        if not ok or not local.exists() or local.stat().st_size == 0:
            raise RuntimeError("err_record_failed")
        get_logger().run("log_record_saved", path=str(local))
        return local

    def stop_async(self) -> None:
        """异步停止（GUI 不阻塞）。"""
        t = threading.Thread(target=self._safe_stop, daemon=True)
        t.start()

    def _safe_stop(self) -> None:
        try:
            self.stop()
        except Exception as exc:
            get_logger().error("err_record_failed", detail=str(exc)[:200])

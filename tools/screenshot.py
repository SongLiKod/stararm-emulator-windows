"""截图工具：ADB screencap，文件自动保存至本地截图目录。"""
import time
from pathlib import Path
from typing import Optional

from adb.adb_manager import AdbManager, AdbError
from config import paths
from log.logger import get_logger


def screenshots_dir() -> Path:
    return paths.screenshots_dir()


def capture_screenshot(adb: AdbManager, port: int, instance_name: str = "",
                       out_dir: Optional[Path] = None) -> Path:
    """截图并自动保存，返回文件路径。"""
    data = adb.screencap_png(port)
    if not data or len(data) < 8:
        raise AdbError("err_screenshot_failed", "")
    out_dir = Path(out_dir) if out_dir else screenshots_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    name = instance_name.replace(" ", "_") if instance_name else "instance"
    path = out_dir / f"stararm-{name}-{ts}.png"
    path.write_bytes(data)
    get_logger().run("log_screenshot_saved", path=str(path))
    return path

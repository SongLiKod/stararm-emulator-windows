"""路径解析：仓库目录、资源目录、用户数据目录（实例/镜像/截图/录屏/日志/共享文件夹）。

支持 STARARM_HOME 环境变量覆盖数据目录（便于测试与便携部署）。
"""
import os
import sys
from pathlib import Path

APP_NAME = "StarARM"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """资源目录（语言包、主题配色、图标）。

    PyInstaller 打包后位于 _MEIPASS/resource，开发环境位于仓库 resource/。
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else Path(sys.executable).resolve().parent
        return base / "resource"
    return repo_root() / "resource"


def app_data_dir() -> Path:
    """用户数据根目录。"""
    env = os.environ.get("STARARM_HOME")
    if env:
        base = Path(env)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    d = app_data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def instances_dir() -> Path:
    return _sub("instances")


def images_dir() -> Path:
    return _sub("mirror") / "images"


def screenshots_dir() -> Path:
    return _sub("screenshots")


def recordings_dir() -> Path:
    return _sub("recordings")


def logs_dir() -> Path:
    return _sub("logs")


def shared_dir() -> Path:
    return _sub("shared")


def backups_dir() -> Path:
    return _sub("backups")


def macros_dir() -> Path:
    return _sub("macros")


def keymaps_dir() -> Path:
    return _sub("keymaps")


def instance_dir(instance_id: str) -> Path:
    return instances_dir() / instance_id

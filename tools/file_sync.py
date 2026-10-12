"""文件交互能力：双向文件推送、共享文件夹双向同步、模拟器文件导出。"""
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from adb.adb_manager import AdbManager
from config import paths
from config.settings import SettingsManager
from log.logger import get_logger

SYNC_MANIFEST = ".stararm-sync.json"
DEFAULT_GUEST_SHARED = "/sdcard/Shared"


class SharedFolderSync:
    """共享文件夹：宿主目录 <-> 模拟器 /sdcard/Shared 双向同步。

    同步状态（manifest）记录两侧 mtime/size，仅传输变化文件；
    支持 GUI 周期自动同步与 CLI / 手动触发。
    """

    def __init__(self, adb: AdbManager, host_dir: Optional[Path] = None,
                 guest_dir: str = DEFAULT_GUEST_SHARED) -> None:
        self._adb = adb
        self._host = Path(host_dir) if host_dir else None
        self._guest = guest_dir
        self._lock = threading.RLock()

    def host_dir(self) -> Path:
        if self._host is not None:
            d = self._host
        else:
            d = paths.shared_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def guest_dir(self) -> str:
        return self._guest

    # ------------------------------------------------------------- manifest
    def _manifest_path(self) -> Path:
        return self.host_dir() / SYNC_MANIFEST

    def _load_manifest(self) -> Dict[str, Dict[str, int]]:
        try:
            data = json.loads(self._manifest_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_manifest(self, manifest: Dict[str, Dict[str, int]]) -> None:
        try:
            self._manifest_path().write_text(
                json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------- push
    def sync_push(self, port: int) -> int:
        """宿主 -> 模拟器：推送新增/变更文件。"""
        with self._lock:
            manifest = self._load_manifest()
            pushed = 0
            host = self.host_dir()
            for f in sorted(host.rglob("*")):
                if not f.is_file() or f.name == SYNC_MANIFEST:
                    continue
                rel = f.relative_to(host).as_posix()
                stat = f.stat()
                record = manifest.get(rel)
                if record and record.get("size") == stat.st_size and \
                        record.get("mtime") == int(stat.st_mtime):
                    continue
                remote = f"{self._guest}/{rel}"
                if self._adb.push(port, str(f), remote):
                    manifest[rel] = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
                    pushed += 1
            self._save_manifest(manifest)
        if pushed:
            get_logger().run("log_shared_pushed", count=pushed)
        return pushed

    # ------------------------------------------------------------- pull
    def sync_pull(self, port: int) -> int:
        """模拟器 -> 宿主：拉取新增/变更文件。"""
        with self._lock:
            manifest = self._load_manifest()
            pulled = 0
            host = self.host_dir()
            for path, mtime, size in self._adb.list_guest_files(port, self._guest):
                rel = path[len(self._guest):].lstrip("/")
                if not rel:
                    continue
                record = manifest.get(rel)
                if record and record.get("size") == size and record.get("mtime") == mtime:
                    continue
                local = host / rel
                local.parent.mkdir(parents=True, exist_ok=True)
                remote = f"{self._guest}/{rel}"
                if self._adb.pull(port, remote, str(local)):
                    manifest[rel] = {"size": size, "mtime": mtime}
                    pulled += 1
            self._save_manifest(manifest)
        if pulled:
            get_logger().run("log_shared_pulled", count=pulled)
        return pulled

    def sync_bidirectional(self, port: int) -> Tuple[int, int]:
        """共享文件夹双向同步：返回 (推送数, 拉取数)。"""
        return self.sync_push(port), self.sync_pull(port)


def push_file(adb: AdbManager, port: int, local: str, remote: str) -> bool:
    """双向文件推送：宿主 -> 模拟器。"""
    ok = adb.push(port, local, remote)
    if ok:
        get_logger().run("log_file_pushed", local=local, remote=remote)
    return ok


def pull_file(adb: AdbManager, port: int, remote: str, local: str) -> bool:
    """模拟器文件导出 / 拉取。"""
    ok = adb.pull(port, remote, local)
    if ok:
        get_logger().run("log_file_pulled", remote=remote, local=local)
    return ok


def export_guest_file(adb: AdbManager, port: int, remote: str, local_target: str) -> bool:
    """模拟器文件导出到宿主任意目录。"""
    return pull_file(adb, port, remote, local_target)


def default_sync(adb: AdbManager, settings: SettingsManager) -> SharedFolderSync:
    s = settings.get()
    return SharedFolderSync(adb, Path(s.shared_folder) if s.shared_folder else None)

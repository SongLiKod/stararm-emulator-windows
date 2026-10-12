"""多实例多开管理：新建、克隆、复制、批量启停、独立资源配置、镜像导入导出、实例数据隔离。

实例数据独立存储：instances/<id>/（instance.json + overlay.qcow2 + data.qcow2 + qemu.pid + serial.log）
支持一键克隆（含磁盘覆盖层完整拷贝）、备份（导出 zip）、还原（导入 zip）。
"""
import copy
import json
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from adb import port_allocator
from adb.adb_manager import AdbManager
from config import paths
from config.settings import SettingsManager
from core.instance import Instance, InstanceConfig, InstanceState
from core.qemu_manager import QemuManager
from core.resource_guard import ResourceGuard
from log.logger import get_logger

CONFIG_FILE = "instance.json"


def used_ports_of(instances: List[Instance]) -> Tuple[Set[int], Set[int], Set[int]]:
    """收集全部实例已占用的 (adb 端口, vnc display, agent 端口)。"""
    adb_ports = {i.config.adb_port for i in instances if i.config.adb_port}
    displays = {i.config.vnc_display for i in instances if i.config.vnc_display >= 0}
    agent_ports = {i.config.agent_port for i in instances if i.config.agent_port}
    return adb_ports, displays, agent_ports


class InstanceManager:
    def __init__(
        self,
        settings: SettingsManager,
        guard: ResourceGuard,
        qemu: QemuManager,
    ) -> None:
        self._settings = settings
        self._guard = guard
        self._qemu = qemu
        self._lock = threading.RLock()
        self._listeners: List[Callable[[Instance], None]] = []

        def save_config(instance: Instance) -> None:
            self.save(instance)

        self._qemu.save_instance_config = save_config
        self._qemu.list_instances = self.list_instances

    # ------------------------------------------------------------- listeners
    def add_listener(self, callback: Callable[[Instance], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self, instance: Instance) -> None:
        for cb in list(self._listeners):
            try:
                cb(instance)
            except Exception:
                pass

    # ------------------------------------------------------------- persistence
    def config_path(self, instance_id: str) -> Path:
        return paths.instance_dir(instance_id) / CONFIG_FILE

    def save(self, instance: Instance) -> None:
        d = paths.instance_dir(instance.id)
        d.mkdir(parents=True, exist_ok=True)
        self.config_path(instance.id).write_text(
            json.dumps(instance.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------- listing
    def list_instances(self) -> List[Instance]:
        instances: List[Instance] = []
        base = paths.instances_dir()
        with self._lock:
            for child in sorted(base.iterdir()):
                f = child / CONFIG_FILE
                if not f.is_file():
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    inst = Instance.from_dict(data)
                    inst.id = child.name
                    instances.append(inst)
                except (OSError, ValueError, TypeError):
                    continue
        self._qemu.sync_runtime_state(instances)
        instances.sort(key=lambda i: i.created_at, reverse=True)
        return instances

    def get(self, instance_id: str) -> Optional[Instance]:
        for inst in self.list_instances():
            if inst.id == instance_id:
                return inst
        return None

    def get_by_name(self, name: str) -> Optional[Instance]:
        for inst in self.list_instances():
            if inst.name == name:
                return inst
        return None

    def resolve(self, id_or_name: str) -> Optional[Instance]:
        return self.get(id_or_name) or self.get_by_name(id_or_name)

    # ------------------------------------------------------------- create / clone / copy
    def create(self, name: str, image_id: str, config: Optional[InstanceConfig] = None) -> Instance:
        """新建实例：分配唯一端口（独立 ADB 端口，无端口冲突），数据目录隔离。"""
        log = get_logger()
        config = config or InstanceConfig()
        existing = self.list_instances()
        used_adb, used_display, used_agent = used_ports_of(existing)
        adb_port, display, agent_port = port_allocator.allocate_ports(used_adb, used_display, used_agent)
        config.adb_port = adb_port
        config.vnc_display = display
        config.agent_port = agent_port

        ok, reason = self._guard.check_create(len(existing))
        if not ok:
            log.error(reason, id=name)
            raise RuntimeError(reason)

        inst = Instance(name=name, image_id=image_id, config=config)
        d = paths.instance_dir(inst.id)
        d.mkdir(parents=True, exist_ok=True)
        self.save(inst)
        log.system("log_instance_created", id=name, image=image_id)
        self._notify(inst)
        return inst

    def clone(self, instance_id: str, new_name: Optional[str] = None) -> Instance:
        """一键克隆：完整拷贝实例数据（含磁盘覆盖层）。"""
        src = self.get(instance_id)
        if src is None:
            raise KeyError(instance_id)
        if self._qemu.is_running(src.id):
            raise RuntimeError("err_instance_running")
        existing = self.list_instances()
        used_adb, used_display, used_agent = used_ports_of(existing)
        adb_port, display, agent_port = port_allocator.allocate_ports(used_adb, used_display, used_agent)
        config = copy.deepcopy(src.config)
        config.adb_port = adb_port
        config.vnc_display = display
        config.agent_port = agent_port
        inst = Instance(
            name=new_name or f"{src.name}-clone",
            image_id=src.image_id,
            config=config,
        )
        dst = paths.instance_dir(inst.id)
        dst.mkdir(parents=True, exist_ok=True)
        self.save(inst)
        for item in ("overlay.qcow2", "data.qcow2", "serial.log"):
            f = paths.instance_dir(src.id) / item
            if f.is_file():
                shutil.copy2(f, dst / item)
        get_logger().system("log_instance_cloned", id=inst.name, source=src.name)
        self._notify(inst)
        return inst

    def copy(self, instance_id: str, new_name: Optional[str] = None) -> Instance:
        """复制：仅复制配置（CPU/内存/磁盘/显示/网络/设备伪装），全新磁盘。"""
        src = self.get(instance_id)
        if src is None:
            raise KeyError(instance_id)
        config = copy.deepcopy(src.config)
        return self.create(new_name or f"{src.name}-copy", src.image_id, config)

    # ------------------------------------------------------------- delete
    def delete(self, instance_id: str, force: bool = False) -> None:
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        if self._qemu.is_running(instance_id):
            if not force:
                raise RuntimeError("err_instance_running")
            self._qemu.stop(inst, force=True, wait=True)
        shutil.rmtree(paths.instance_dir(instance_id), ignore_errors=True)
        get_logger().system("log_instance_deleted", id=inst.name)
        self._notify(inst)

    # ------------------------------------------------------------- config
    def update_config(self, instance_id: str, **fields) -> Instance:
        """更新单实例配置（批量配置资源参数可循环调用本方法实现）。"""
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        cfg = inst.config
        device_fields = {k for k in fields if k.startswith("device.")}
        for key, value in fields.items():
            if key.startswith("device."):
                setattr(cfg.device, key[len("device."):], value)
            elif key.startswith("gps."):
                setattr(cfg.gps, key[len("gps."):], value)
            elif key.startswith("battery."):
                setattr(cfg.battery, key[len("battery."):], value)
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        if device_fields:
            pass
        self.save(inst)
        get_logger().system("log_instance_config_updated", id=inst.name)
        self._notify(inst)
        return inst

    # ------------------------------------------------------------- start / stop
    def start(self, instance_id: str, wait: bool = False) -> Instance:
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        self._qemu.start(inst, wait=wait)
        if wait and inst.state not in (InstanceState.RUNNING,):
            raise RuntimeError(inst.last_error or "err_start_failed")
        return inst

    def stop(self, instance_id: str, force: bool = False, wait: bool = False) -> Instance:
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        self._qemu.stop(inst, force=force, wait=wait)
        return inst

    def batch_start(self, ids: List[str]) -> List[Tuple[str, bool, str]]:
        """批量启动：逐个启动互不影响，返回 (id, ok, error)。"""
        results = []
        for iid in ids:
            try:
                self.start(iid)
                results.append((iid, True, ""))
            except Exception as exc:
                results.append((iid, False, str(exc)))
        get_logger().system("log_batch_start_done", ok=sum(1 for _, okk, _ in results if okk),
                            fail=sum(1 for _, okk, _ in results if not okk))
        return results

    def batch_stop(self, ids: List[str], force: bool = False) -> List[Tuple[str, bool, str]]:
        """批量停止。"""
        results = []
        for iid in ids:
            try:
                self.stop(iid, force=force, wait=True)
                results.append((iid, True, ""))
            except Exception as exc:
                results.append((iid, False, str(exc)))
        get_logger().system("log_batch_stop_done", ok=sum(1 for _, okk, _ in results if okk),
                            fail=sum(1 for _, okk, _ in results if not okk))
        return results

    def batch_delete(self, ids: List[str], force: bool = False) -> List[Tuple[str, bool, str]]:
        """批量删除。"""
        results = []
        for iid in ids:
            try:
                self.delete(iid, force=force)
                results.append((iid, True, ""))
            except Exception as exc:
                results.append((iid, False, str(exc)))
        get_logger().system("log_batch_delete_done", ok=sum(1 for _, okk, _ in results if okk),
                            fail=sum(1 for _, okk, _ in results if not okk))
        return results

    def batch_configure(self, ids: List[str], **fields) -> List[Tuple[str, bool, str]]:
        """批量配置资源参数。"""
        results = []
        for iid in ids:
            try:
                self.update_config(iid, **fields)
                results.append((iid, True, ""))
            except Exception as exc:
                results.append((iid, False, str(exc)))
        get_logger().system("log_batch_configure_done", ok=sum(1 for _, okk, _ in results if okk),
                            fail=sum(1 for _, okk, _ in results if not okk))
        return results

    # ------------------------------------------------------------- export / import / backup
    def export_instance(self, instance_id: str, zip_path: Path) -> Path:
        """导出实例（镜像导出/实例迁移）。"""
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        if self._qemu.is_running(instance_id):
            raise RuntimeError("err_instance_running")
        zip_path = Path(zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            d = paths.instance_dir(instance_id)
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.name not in ("qemu.pid",):
                    zf.write(f, f.relative_to(d))
        get_logger().system("log_instance_exported", id=inst.name, path=str(zip_path))
        return zip_path

    def import_instance(self, zip_path: Path, new_name: Optional[str] = None) -> Instance:
        """导入实例（还原备份 / 迁移导入）。"""
        zip_path = Path(zip_path)
        if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
            raise RuntimeError("err_import_invalid")
        import json as _json
        with zipfile.ZipFile(zip_path) as zf:
            try:
                data = _json.loads(zf.read(CONFIG_FILE).decode("utf-8"))
            except (KeyError, ValueError) as exc:
                raise RuntimeError("err_import_invalid") from exc
        inst = Instance.from_dict(data)
        existing = self.list_instances()
        used_adb, used_display, used_agent = used_ports_of(existing)
        adb_port, display, agent_port = port_allocator.allocate_ports(used_adb, used_display, used_agent)
        inst.config.adb_port = adb_port
        inst.config.vnc_display = display
        inst.config.agent_port = agent_port
        inst.id = f"i{int(time.time() * 1000):x}{len(existing)}"[:12]
        if new_name:
            inst.name = new_name
        inst.state = InstanceState.STOPPED
        inst.last_error = ""
        inst.last_error_detail = ""
        d = paths.instance_dir(inst.id)
        d.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                if member in ("qemu.pid",) or member.startswith("/") or ".." in member:
                    continue
                target = d / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        self.save(inst)
        get_logger().system("log_instance_imported", id=inst.name)
        self._notify(inst)
        return inst

    def backup(self, instance_id: str) -> Path:
        """一键备份：导出到内置备份目录。"""
        inst = self.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        ts = time.strftime("%Y%m%d-%H%M%S")
        target = paths.backups_dir() / f"{inst.name}-{ts}.zip"
        return self.export_instance(instance_id, target)

    def restore(self, zip_path: Path, new_name: Optional[str] = None) -> Instance:
        """还原备份。"""
        return self.import_instance(zip_path, new_name)

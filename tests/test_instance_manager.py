"""实例管理测试：新建/克隆/复制/删除/导入导出/批量/数据隔离。"""
import json
from unittest.mock import MagicMock

import pytest

from config.settings import SettingsManager
from core.instance import InstanceConfig
from core.instance_manager import InstanceManager, used_ports_of
from core.resource_guard import ResourceGuard


def make_manager(max_instances: int = 16) -> InstanceManager:
    settings = SettingsManager()
    settings.update(max_instances=max_instances)
    guard = ResourceGuard(settings)
    qemu = MagicMock()
    qemu.is_running.return_value = False
    return InstanceManager(settings, guard, qemu)


def test_create_allocates_unique_ports_and_isolated_dir(stararm_home):
    m = make_manager()
    a = m.create("inst-a", "aosp-13-arm64")
    b = m.create("inst-b", "aosp-13-arm64")
    # 数据目录隔离
    assert (stararm_home / "instances" / a.id / "instance.json").is_file()
    assert (stararm_home / "instances" / b.id / "instance.json").is_file()
    assert a.id != b.id
    # 独立 ADB 端口，无端口冲突
    assert a.config.adb_port != b.config.adb_port
    assert a.config.vnc_display != b.config.vnc_display
    assert a.config.agent_port != b.config.agent_port


def test_list_and_get(stararm_home):
    m = make_manager()
    inst = m.create("one", "aosp-14-arm64")
    assert [i.id for i in m.list_instances()] == [inst.id]
    assert m.get(inst.id).name == "one"
    assert m.resolve("one").id == inst.id
    assert m.resolve("no-such") is None


def test_clone_copies_overlay_and_gets_new_ports(stararm_home):
    m = make_manager()
    src = m.create("src", "aosp-13-arm64")
    overlay = stararm_home / "instances" / src.id / "overlay.qcow2"
    overlay.write_bytes(b"fake-overlay-data")
    clone = m.clone(src.id, "cloned")
    assert clone.id != src.id
    assert clone.config.adb_port != src.config.adb_port
    assert (stararm_home / "instances" / clone.id / "overlay.qcow2").read_bytes() \
        == b"fake-overlay-data"
    assert clone.name == "cloned"


def test_copy_duplicates_config_with_fresh_disk(stararm_home):
    m = make_manager()
    src = m.create("src", "aosp-15-arm64", InstanceConfig(cpu_cores=6, memory_mb=6144))
    copy = m.copy(src.id, "copied")
    assert copy.config.cpu_cores == 6
    assert copy.config.memory_mb == 6144
    assert not (stararm_home / "instances" / copy.id / "overlay.qcow2").exists()


def test_delete(stararm_home):
    m = make_manager()
    inst = m.create("gone", "aosp-13-arm64")
    m.delete(inst.id)
    assert m.get(inst.id) is None
    assert not (stararm_home / "instances" / inst.id).exists()


def test_export_import_roundtrip(stararm_home, tmp_path):
    m = make_manager()
    inst = m.create("mover", "aosp-12-arm64")
    (stararm_home / "instances" / inst.id / "overlay.qcow2").write_bytes(b"data")
    zip_path = m.export_instance(inst.id, tmp_path / "inst.zip")
    assert zip_path.is_file()
    imported = m.import_instance(zip_path, "moved-back")
    assert imported.name == "moved-back"
    assert (stararm_home / "instances" / imported.id / "overlay.qcow2").read_bytes() \
        == b"data"
    assert imported.config.adb_port != inst.config.adb_port


def test_backup_and_restore(stararm_home):
    m = make_manager()
    inst = m.create("bak", "aosp-11-arm64")
    path = m.backup(inst.id)
    assert path.is_file()
    restored = m.restore(path, "restored")
    assert restored.name == "restored"


def test_update_config_nested_fields(stararm_home):
    m = make_manager()
    inst = m.create("cfg", "aosp-13-arm64")
    m.update_config(inst.id, **{
        "cpu_cores": 8,
        "device.brand": "Xiaomi",
        "gps.latitude": 31.23,
        "battery.level": 55,
        "battery.charging": False,
    })
    loaded = m.get(inst.id)
    assert loaded.config.cpu_cores == 8
    assert loaded.config.device.brand == "Xiaomi"
    assert loaded.config.gps.latitude == 31.23
    assert loaded.config.battery.level == 55
    assert loaded.config.battery.charging is False


def test_max_instances_guard(stararm_home):
    m = make_manager(max_instances=2)
    m.create("a", "aosp-13-arm64")
    m.create("b", "aosp-13-arm64")
    with pytest.raises(RuntimeError) as excinfo:
        m.create("c", "aosp-13-arm64")
    assert "err_max_instances" in str(excinfo.value.args[0])


def test_batch_configure_and_results(stararm_home):
    m = make_manager()
    a = m.create("a", "aosp-13-arm64")
    b = m.create("b", "aosp-13-arm64")
    results = m.batch_configure([a.id, b.id], cpu_cores=2)
    assert all(ok for _, ok, _ in results)
    assert m.get(a.id).config.cpu_cores == 2


def test_used_ports_of(stararm_home):
    m = make_manager()
    a = m.create("a", "aosp-13-arm64")
    b = m.create("b", "aosp-13-arm64")
    adb_ports, displays, agents = used_ports_of(m.list_instances())
    assert a.config.adb_port in adb_ports
    assert b.config.adb_port in adb_ports
    assert len(displays) == 2
    assert len(agents) == 2

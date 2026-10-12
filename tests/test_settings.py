"""全局设置测试：默认值、持久化、校验、观察者。"""
import json

from config.settings import GlobalSettings, SettingsManager


def test_defaults(stararm_home):
    m = SettingsManager()
    s = m.get()
    assert s.theme_mode == "system"
    assert s.language == "system"
    assert s.max_instances >= 1
    assert s.max_total_cpu_cores == 0
    assert s.max_total_memory_gb == 0


def test_save_and_reload(stararm_home):
    m = SettingsManager()
    m.update(theme_mode="dark", language="en_US", max_instances=5)
    # 重启不重置：重新加载读取持久化文件
    m2 = SettingsManager()
    assert m2.get().theme_mode == "dark"
    assert m2.get().language == "en_US"
    assert m2.get().max_instances == 5
    data = json.loads((stararm_home / "settings.json").read_text(encoding="utf-8"))
    assert data["theme_mode"] == "dark"


def test_invalid_values_rejected(stararm_home):
    m = SettingsManager()
    try:
        m.update(theme_mode="pink")
        raise AssertionError("should reject invalid theme")
    except ValueError:
        pass
    try:
        m.update(max_instances=0)
        raise AssertionError("should reject zero instances")
    except ValueError:
        pass


def test_listener_called(stararm_home):
    m = SettingsManager()
    seen = []
    m.add_listener(lambda key, value: seen.append((key, value)))
    m.update(language="zh_CN")
    assert ("language", "zh_CN") in seen


def test_dataclass_roundtrip(stararm_home):
    m = SettingsManager()
    m.update(qemu_path="C:/qemu/qemu-system-aarch64.exe",
             shared_folder="C:/shared")
    assert m.get().qemu_path.endswith("qemu-system-aarch64.exe")
    assert m.get().shared_folder == "C:/shared"

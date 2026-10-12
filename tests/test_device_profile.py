"""设备伪装 / GPS / 电池测试：随机参数生成、属性构建、开机应用。"""
from core.guest_agent import GuestAgentClient
from core.instance import InstanceConfig
from tools.device_profile import (
    build_fingerprint, build_props, generate_imei, generate_profile,
    luhn_checksum_digit, apply_profile, ANTI_EMULATOR_PROPS,
)


def luhn_full_valid(number: str) -> bool:
    """独立实现：完整 15 位号码的标准 Luhn 校验（从右起第 2 位加倍）。"""
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def test_imei_luhn_known_vectors():
    # 已知有效 IMEI 与公开载荷向量（外部标准，非自洽）
    assert luhn_checksum_digit("49015420323751") == "8"
    assert luhn_checksum_digit("12345678901234") == "7"
    assert luhn_full_valid("490154203237518")
    assert luhn_full_valid("123456789012347")


def test_imei_luhn_valid():
    for _ in range(20):
        imei = generate_imei()
        assert len(imei) == 15 and imei.isdigit()
        assert luhn_checksum_digit(imei[:14]) == imei[14]
        assert luhn_full_valid(imei)


def test_serial_and_android_id_format():
    p = generate_profile()
    assert len(p.serial) == 10
    assert len(p.android_id) == 16
    int(p.android_id, 16)  # 16 位十六进制
    assert p.brand and p.model and p.manufacturer
    assert p.fingerprint == build_fingerprint(p.brand, p.model, 13, p.serial)


def test_build_props_includes_anti_emulator_signatures():
    p = generate_profile()
    props = build_props(p)
    assert props["ro.product.brand"] == p.brand
    assert props["ro.product.model"] == p.model
    assert props["ro.serialno"] == p.serial
    assert props["ro.build.fingerprint"] == p.fingerprint
    # 弱化 QEMU 模拟器特征
    for key in ("ro.kernel.qemu", "ro.boot.qemu"):
        assert key in props
        assert props[key] == ANTI_EMULATOR_PROPS[key]
        assert props[key] == "0"


def test_apply_profile_uses_adb_and_reports(fake_adb):
    cfg = InstanceConfig()
    cfg.device = generate_profile()
    cfg.gps.latitude = 1.5
    cfg.gps.longitude = 2.5
    cfg.battery.level = 66
    cfg.battery.charging = False
    report = apply_profile(fake_adb, None, cfg, android_version=13)
    items = dict(report)
    assert set(items) == {"props", "android_id", "imei", "gps", "battery"}
    # agent 不可用 -> 走 ADB 属性通道（逐条 setprop 回退）
    names = [c[0] for c in fake_adb.calls]
    assert "setprop" in names
    assert any(c[0] == "settings_put_secure" and c[2] == "android_id"
               for c in fake_adb.calls)
    # 电池模拟（放电状态）
    battery_calls = [c for c in fake_adb.calls if c[0] == "battery_set"]
    assert battery_calls and battery_calls[0][2] == 66 and battery_calls[0][3] is False
    # 代理不可用：GPS / IMEI / 属性失败如实上报
    assert items["gps"] is False
    assert items["imei"] is False


def test_apply_profile_with_agent_primary(fake_adb):
    class FakeAgent:
        def set_props(self, props):
            return True

        def set_gps(self, lat, lng):
            return lat == 1.5 and lng == 2.5

        def set_clipboard(self, text):
            return True

        def get_clipboard(self):
            return "clip"

        def set_imei(self, imei):
            return True

    cfg = InstanceConfig()
    cfg.device = generate_profile()
    cfg.device.imei = generate_imei()
    cfg.gps.latitude = 1.5
    cfg.gps.longitude = 2.5
    report = dict(apply_profile(fake_adb, FakeAgent(), cfg, android_version=15))
    assert report["props"] is True
    assert report["gps"] is True
    assert report["imei"] is True
    # agent 成功时不再逐条走 ADB setprop 回退
    assert not any(c[0] == "setprop" for c in fake_adb.calls)


def test_guest_agent_client_offline_returns_none():
    agent = GuestAgentClient(port=1, timeout=0.2)
    assert agent._transact({"cmd": "gps", "lat": 0, "lng": 0}) is None
    assert agent.set_gps(0.0, 0.0) is False
    assert agent.get_clipboard() is None
    assert agent.set_imei("123") is False

"""虚拟化检测测试：多源判定（固件 / 虚拟机监控程序 / WHPX 功能与库）与误报防护。"""
from core import virtualization as vt_mod
from core.virtualization import (
    REASON_FIRMWARE, REASON_OK, REASON_UNKNOWN, REASON_WHPX,
    VirtualizationStatus, detect_virtualization, parse_probe,
)


def _detect(monkeypatch, probe, whpx: bool) -> VirtualizationStatus:
    monkeypatch.setattr(vt_mod, "_run_probe", lambda: dict(probe))
    monkeypatch.setattr(vt_mod, "whpx_dll_available", lambda: whpx)
    return detect_virtualization()


def test_parse_probe_json():
    out = parse_probe('{"firmware": true, "hypervisor": false, "whpx_feature": true}')
    assert out == {"firmware": True, "hypervisor": False, "whpx_feature": True}


def test_parse_probe_tolerates_missing_and_invalid():
    assert parse_probe("") == {}
    assert parse_probe("not json") == {}
    assert parse_probe('{"firmware": "true"}') == {}
    assert parse_probe("[1,2]") == {}


def test_ok_when_firmware_and_whpx(monkeypatch):
    status = _detect(monkeypatch, {"firmware": True, "hypervisor": False}, whpx=True)
    assert status.reason == REASON_OK
    assert status.accelerated is True
    assert status.method == "whpx"


def test_hypervisor_running_overrides_false_firmware(monkeypatch):
    """Hyper-V/WSL2 运行时固件常误报 False，必须判定为可用（否则误报"未开启"）。"""
    status = _detect(monkeypatch, {"firmware": False, "hypervisor": True}, whpx=True)
    assert status.reason == REASON_OK
    assert status.accelerated is True
    assert status.firmware_disabled is False


def test_firmware_disabled_without_hypervisor(monkeypatch):
    status = _detect(monkeypatch, {"firmware": False, "hypervisor": False}, whpx=False)
    assert status.reason == REASON_FIRMWARE
    assert status.accelerated is False
    assert status.method == "tcg"
    assert status.firmware_disabled is True


def test_firmware_ok_but_whpx_missing(monkeypatch):
    """BIOS 已开启、仅 Windows 虚拟机监控程序平台未启用：应提示 whpx 而非"未开启"。"""
    status = _detect(monkeypatch, {"firmware": True, "hypervisor": False}, whpx=False)
    assert status.reason == REASON_WHPX
    assert status.needs_whpx is True
    assert status.firmware_disabled is False
    assert status.accelerated is False


def test_whpx_feature_enabled_counts_as_available(monkeypatch):
    status = _detect(monkeypatch, {"whpx_feature": True}, whpx=False)
    assert status.whpx_available is True
    assert status.reason == REASON_OK


def test_unknown_when_probe_fails_and_no_whpx(monkeypatch):
    status = _detect(monkeypatch, {}, whpx=False)
    assert status.reason == REASON_UNKNOWN
    assert status.firmware_unknown is True
    assert status.accelerated is False


def test_whpx_available_without_probe(monkeypatch):
    """WHPX 库存在时即使 WMI 全部失败，也应尝试硬件加速。"""
    status = _detect(monkeypatch, {}, whpx=True)
    assert status.reason == REASON_OK
    assert status.accelerated is True


def test_whpx_dll_available_returns_bool():
    assert isinstance(vt_mod.whpx_dll_available(), bool)

"""键鼠触摸映射测试：动作模型、映射档案、按键派发。"""
import pytest

from tools.keymap import InputAction, KeyMappingProfile, apply_key


def test_action_roundtrip_and_apply(fake_adb):
    action = InputAction(type="tap", x=30, y=40)
    restored = InputAction.from_dict(action.to_dict())
    assert restored.x == 30 and restored.y == 40
    restored.apply(fake_adb, 5555)
    assert ("input_tap", 5555, 30, 40) in fake_adb.calls

    swipe = InputAction(type="swipe", x=1, y=2, x2=3, y2=4, duration_ms=250)
    swipe.apply(fake_adb, 5555)
    assert ("input_swipe", 5555, 1, 2, 3, 4, 250) in fake_adb.calls

    key = InputAction(type="key", keycode=4)
    key.apply(fake_adb, 5555)
    assert ("input_key", 5555, 4) in fake_adb.calls

    text = InputAction(type="text", text="hello")
    text.apply(fake_adb, 5555)
    assert ("input_text", 5555, "hello") in fake_adb.calls


def test_invalid_action_type():
    with pytest.raises(ValueError):
        InputAction(type="dance").validate()


def test_profile_save_load(stararm_home):
    profile = KeyMappingProfile(name="game", bindings={
        "W": InputAction(type="tap", x=100, y=300),
        "SPACE": InputAction(type="key", keycode=66),
    })
    path = profile.save()
    assert path.is_file()
    loaded = KeyMappingProfile.load("game")
    assert loaded is not None
    assert loaded.bindings["W"].x == 100
    assert loaded.bindings["SPACE"].keycode == 66
    assert KeyMappingProfile.load("missing") is None


def test_apply_key_dispatches_mapping(fake_adb):
    profile = KeyMappingProfile(name="m", bindings={
        "W": InputAction(type="tap", x=5, y=6),
    })
    assert apply_key(fake_adb, 5555, profile, "W") is True
    assert ("input_tap", 5555, 5, 6) in fake_adb.calls
    # 未映射按键返回 False（走 RFB 按键注入）
    assert apply_key(fake_adb, 5555, profile, "Q") is False


def test_profile_json_structure(stararm_home):
    import json
    KeyMappingProfile(name="p", bindings={
        "A": InputAction(type="tap", x=1, y=2),
    }).save()
    data = json.loads((stararm_home / "keymaps" / "p.json").read_text(encoding="utf-8"))
    assert data["name"] == "p"
    assert data["bindings"]["A"]["type"] == "tap"

"""宏脚本测试：步骤模型、回放、保存载入、循环与取消。"""
import json
import threading

from tools.macro import Macro, MacroRunner, MacroStep


def test_macro_step_roundtrip():
    step = MacroStep(type="tap", x=100, y=200)
    data = step.to_dict()
    restored = MacroStep.from_dict(data)
    assert restored.type == "tap" and restored.x == 100 and restored.y == 200


def test_invalid_step_type_rejected():
    import pytest
    with pytest.raises(ValueError):
        MacroStep(type="explode").validate()


def test_macro_save_load(stararm_home):
    macro = Macro(name="test-macro", loop_count=3, steps=[
        MacroStep(type="tap", x=1, y=2),
        MacroStep(type="sleep", seconds=0.01),
    ])
    macro.save()
    loaded = Macro.load("test-macro")
    assert loaded is not None
    assert loaded.name == "test-macro"
    assert loaded.loop_count == 3
    assert [s.type for s in loaded.steps] == ["tap", "sleep"]
    assert Macro.load("missing") is None


def test_runner_executes_steps_in_order(fake_adb):
    macro = Macro(name="run", loop_count=2, steps=[
        MacroStep(type="tap", x=10, y=20),
        MacroStep(type="swipe", x=1, y=2, x2=3, y2=4, duration_ms=500),
        MacroStep(type="key", keycode=66),
        MacroStep(type="text", text="hi"),
        MacroStep(type="sleep", seconds=0.01),
    ])
    executed = MacroRunner(fake_adb, 5555).run(macro)
    assert executed == 8  # 4 动作 x 2 循环
    names = [c[0] for c in fake_adb.calls]
    assert names.count("input_tap") == 2
    assert names.count("input_swipe") == 2
    assert names.count("input_key") == 2
    assert names.count("input_text") == 2
    swipe = [c for c in fake_adb.calls if c[0] == "input_swipe"][0]
    assert swipe == ("input_swipe", 5555, 1, 2, 3, 4, 500)
    tap = [c for c in fake_adb.calls if c[0] == "input_tap"][0]
    assert tap == ("input_tap", 5555, 10, 20)


def test_runner_cancel(fake_adb):
    macro = Macro(name="cancel", loop_count=100, steps=[
        MacroStep(type="tap", x=0, y=0),
        MacroStep(type="sleep", seconds=0.05),
    ])
    cancel = threading.Event()
    cancel.set()
    executed = MacroRunner(fake_adb, 5555).run(macro, cancel)
    assert executed == 0


def test_macro_to_dict_jsonable():
    macro = Macro(name="j", steps=[MacroStep(type="tap", x=1, y=1)])
    data = json.loads(json.dumps(macro.to_dict()))
    restored = Macro.from_dict(data)
    assert restored.steps[0].x == 1

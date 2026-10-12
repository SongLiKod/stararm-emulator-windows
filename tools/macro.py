"""自定义宏脚本：动作序列录制编排、导入导出、批量回放。

宏 JSON 存储于用户数据目录 macros/，步骤类型：tap / swipe / key / text / sleep。
支持循环次数，支持取消（GUI 关闭宏运行时触发）。
"""
import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from adb.adb_manager import AdbManager
from config import paths
from log.logger import get_logger
from tools.keymap import InputAction

STEP_TYPES = ("tap", "swipe", "key", "text", "sleep")


@dataclass
class MacroStep:
    type: str = "tap"
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    duration_ms: int = 300
    keycode: int = 0
    text: str = ""
    seconds: float = 0.5

    def validate(self) -> None:
        if self.type not in STEP_TYPES:
            raise ValueError(f"invalid step type: {self.type}")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "MacroStep":
        s = MacroStep()
        for k, v in (data or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        s.validate()
        return s

    def to_action(self) -> Optional[InputAction]:
        if self.type == "sleep":
            return None
        return InputAction(
            type=self.type, x=self.x, y=self.y, x2=self.x2, y2=self.y2,
            duration_ms=self.duration_ms, keycode=self.keycode, text=self.text,
        )


@dataclass
class Macro:
    name: str = "macro"
    steps: List[MacroStep] = field(default_factory=list)
    loop_count: int = 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "loop_count": self.loop_count,
            "steps": [s.to_dict() for s in self.steps],
        }

    @staticmethod
    def from_dict(data: dict) -> "Macro":
        m = Macro(
            name=str((data or {}).get("name", "macro")),
            loop_count=max(1, int((data or {}).get("loop_count", 1) or 1)),
        )
        for step in (data or {}).get("steps") or []:
            try:
                m.steps.append(MacroStep.from_dict(step))
            except ValueError:
                continue
        return m

    def save(self) -> Path:
        d = paths.macros_dir()
        d.mkdir(parents=True, exist_ok=True)
        safe = self.name.replace(" ", "_")
        path = d / f"{safe}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    @staticmethod
    def load(name: str) -> Optional["Macro"]:
        safe = str(name).replace(" ", "_")
        path = paths.macros_dir() / f"{safe}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Macro.from_dict(data)
        except (OSError, ValueError):
            return None

    @staticmethod
    def list_macros() -> list:
        return sorted(p.stem for p in paths.macros_dir().glob("*.json"))


class MacroRunner:
    """宏回放器：顺序执行步骤；cancel 可随时中止。"""

    def __init__(self, adb: AdbManager, port: int) -> None:
        self._adb = adb
        self._port = port

    def run(self, macro: Macro, cancel: Optional[threading.Event] = None) -> int:
        log = get_logger()
        log.run("log_macro_started", id=macro.name, loops=macro.loop_count)
        executed = 0
        for loop in range(macro.loop_count):
            for step in macro.steps:
                if cancel is not None and cancel.is_set():
                    log.run("log_macro_cancelled", id=macro.name)
                    return executed
                if step.type == "sleep":
                    time.sleep(max(0.0, float(step.seconds)))
                    continue
                action = step.to_action()
                if action is None:
                    continue
                try:
                    action.apply(self._adb, self._port)
                    executed += 1
                except Exception as exc:
                    log.error("log_macro_step_failed", id=macro.name,
                              detail=str(exc)[:200])
        log.run("log_macro_finished", id=macro.name, steps=executed)
        return executed

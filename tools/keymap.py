"""键鼠触摸映射：宿主键 -> 虚拟机触摸/按键动作（WASD 映射到屏幕坐标等）。

映射档案 JSON 存储于用户数据目录 keymaps/，可供宏脚本与手柄适配复用同一动作模型。
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional

from adb.adb_manager import AdbManager
from config import paths

ACTION_TYPES = ("tap", "swipe", "key", "text")


@dataclass
class InputAction:
    """一个虚拟机输入动作：点击 / 滑动 / 按键 / 文本输入。"""
    type: str = "tap"
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    duration_ms: int = 300
    keycode: int = 0
    text: str = ""

    def validate(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ValueError(f"invalid action type: {self.type}")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "InputAction":
        a = InputAction()
        for k, v in (data or {}).items():
            if hasattr(a, k):
                setattr(a, k, v)
        a.validate()
        return a

    def apply(self, adb: AdbManager, port: int) -> None:
        """通过 ADB input 派发到虚拟机。"""
        if self.type == "tap":
            adb.input_tap(port, self.x, self.y)
        elif self.type == "swipe":
            adb.input_swipe(port, self.x, self.y, self.x2, self.y2, self.duration_ms)
        elif self.type == "key":
            adb.input_key(port, self.keycode)
        elif self.type == "text":
            adb.input_text(port, self.text)


@dataclass
class KeyMappingProfile:
    """键位映射档案：宿主键名 -> 虚拟机动作。"""
    name: str = "default"
    bindings: Dict[str, InputAction] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
        }

    @staticmethod
    def from_dict(data: dict) -> "KeyMappingProfile":
        p = KeyMappingProfile(name=str((data or {}).get("name", "default")))
        for key, value in ((data or {}).get("bindings") or {}).items():
            try:
                p.bindings[str(key)] = InputAction.from_dict(value)
            except ValueError:
                continue
        return p

    def save(self) -> Path:
        d = paths.keymaps_dir()
        d.mkdir(parents=True, exist_ok=True)
        safe = self.name.replace(" ", "_")
        path = d / f"{safe}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    @staticmethod
    def load(name: str) -> Optional["KeyMappingProfile"]:
        safe = str(name).replace(" ", "_")
        path = paths.keymaps_dir() / f"{safe}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return KeyMappingProfile.from_dict(data)
        except (OSError, ValueError):
            return None

    @staticmethod
    def list_profiles() -> list:
        return sorted(p.stem + ".json" for p in paths.keymaps_dir().glob("*.json"))


def apply_key(adb: AdbManager, port: int, profile: KeyMappingProfile, key: str) -> bool:
    """宿主键按下 -> 派发映射动作；未映射返回 False。"""
    action = profile.bindings.get(key)
    if action is None:
        return False
    action.apply(adb, port)
    return True

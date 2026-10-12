"""手柄适配：Windows XInput（ctypes 直接调用，无第三方依赖）。

- 按键映射到虚拟机 tap / key / swipe 动作（复用键位映射 InputAction 模型）
- 摇杆映射为虚拟机触摸移动（adb input motionevent DOWN/MOVE/UP）
- 手柄不存在 / XInput 不可用时自动禁用，不影响其他功能
本模块无 GUI 依赖，由 GUI 定时器驱动 tick()。
"""
import ctypes
import json
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from adb.adb_manager import AdbManager
from config import paths
from log.logger import get_logger
from tools.keymap import InputAction

# XInput 按键位掩码
BUTTON_DPAD_UP = 0x0001
BUTTON_DPAD_DOWN = 0x0002
BUTTON_DPAD_LEFT = 0x0004
BUTTON_DPAD_RIGHT = 0x0008
BUTTON_START = 0x0010
BUTTON_BACK = 0x0020
BUTTON_L3 = 0x0040
BUTTON_R3 = 0x0080
BUTTON_LB = 0x0100
BUTTON_RB = 0x0200
BUTTON_A = 0x1000
BUTTON_B = 0x2000
BUTTON_X = 0x4000
BUTTON_Y = 0x8000

BUTTON_NAMES = {
    "A": BUTTON_A, "B": BUTTON_B, "X": BUTTON_X, "Y": BUTTON_Y,
    "LB": BUTTON_LB, "RB": BUTTON_RB, "BACK": BUTTON_BACK, "START": BUTTON_START,
    "L3": BUTTON_L3, "R3": BUTTON_R3,
    "DPAD_UP": BUTTON_DPAD_UP, "DPAD_DOWN": BUTTON_DPAD_DOWN,
    "DPAD_LEFT": BUTTON_DPAD_LEFT, "DPAD_RIGHT": BUTTON_DPAD_RIGHT,
}
BUTTON_NAMES_INV = {v: k for k, v in BUTTON_NAMES.items()}

DEADZONE = 6000
THUMB_RANGE = 32768.0

GAMEPAD_CONFIG = "gamepad.json"


class _XInputGamepad:
    """单手柄 XInput 封装（xinput1_4 / xinput9_1_0）。"""

    def __init__(self) -> None:
        self._dll: Optional[ctypes.CDLL] = None
        for name in ("xinput1_4.dll", "xinput9_1_0.dll"):
            try:
                self._dll = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        self._state = None
        if self._dll is not None:
            class _Gamepad(ctypes.Structure):
                _fields_ = [
                    ("wButtons", ctypes.c_ushort),
                    ("bLeftTrigger", ctypes.c_ubyte),
                    ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short),
                    ("sThumbLY", ctypes.c_short),
                    ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short),
                ]
            class _State(ctypes.Structure):
                _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _Gamepad)]
            self._state = _State()
        self._last_packet = 0

    @property
    def available(self) -> bool:
        return self._dll is not None

    def poll(self, user_index: int = 0):
        """返回 (wButtons, lx, ly, rx, ry)；未连接返回 None。"""
        if self._dll is None or self._state is None:
            return None
        result = self._dll.XInputGetState(user_index, ctypes.byref(self._state))
        if result != 0:
            return None
        if self._state.dwPacketNumber == self._last_packet:
            gp = self._state.Gamepad
            return gp.wButtons, gp.sThumbLX, gp.sThumbLY, gp.sThumbRX, gp.sThumbRY
        self._last_packet = self._state.dwPacketNumber
        gp = self._state.Gamepad
        return gp.wButtons, gp.sThumbLX, gp.sThumbLY, gp.sThumbRX, gp.sThumbRY


class GamepadBridge:
    """手柄 -> 虚拟机输入桥接。tick() 由 GUI QTimer 驱动（约 30Hz）。"""

    def __init__(self, adb: AdbManager, port: int, screen_w: int = 1280, screen_h: int = 720) -> None:
        self._adb = adb
        self._port = port
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._pad = _XInputGamepad()
        self._mapping: Dict[str, InputAction] = {}
        self._enabled = False
        self._prev_buttons = 0
        self._stick_touching = False
        self._last_x = 0
        self._last_y = 0
        self._lock = threading.RLock()
        self.load_mapping()

    # ------------------------------------------------------------- mapping
    def mapping_path(self) -> Path:
        return paths.app_data_dir() / GAMEPAD_CONFIG

    def load_mapping(self) -> Dict[str, InputAction]:
        try:
            data = json.loads(self.mapping_path().read_text(encoding="utf-8"))
            self._mapping = {
                k: InputAction.from_dict(v) for k, v in (data or {}).items()
                if k in BUTTON_NAMES
            }
        except (OSError, ValueError, TypeError):
            self._mapping = {}
        return self._mapping

    def save_mapping(self) -> None:
        try:
            self.mapping_path().write_text(
                json.dumps({k: v.to_dict() for k, v in self._mapping.items()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass

    def set_mapping(self, mapping: Dict[str, InputAction]) -> None:
        with self._lock:
            self._mapping = dict(mapping)
            self.save_mapping()

    @property
    def enabled(self) -> bool:
        return self._enabled and self._pad.available

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def available(self) -> bool:
        return self._pad.available

    def set_screen(self, w: int, h: int) -> None:
        self._screen_w = max(1, int(w))
        self._screen_h = max(1, int(h))

    # ------------------------------------------------------------- tick
    def tick(self, on_status: Optional[Callable[[bool], None]] = None) -> None:
        """轮询手柄并派发输入（GUI 定时器驱动）。"""
        if not self.enabled:
            return
        state = self._pad.poll()
        if state is None:
            if on_status:
                on_status(False)
            return
        if on_status:
            on_status(True)
        buttons, lx, ly, _rx, _ry = state
        with self._lock:
            rising = buttons & ~self._prev_buttons
            falling = ~buttons & self._prev_buttons
            self._prev_buttons = buttons
        # 按键边沿触发映射动作
        for name, action in list(self._mapping.items()):
            mask = BUTTON_NAMES.get(name, 0)
            if mask and (rising & mask):
                try:
                    action.apply(self._adb, self._port)
                except Exception as exc:
                    get_logger().run("log_gamepad_action_failed", level="WARNING",
                                      detail=str(exc)[:200])
        # 左摇杆 -> 触摸移动（motionevent DOWN/MOVE/UP）
        try:
            self._handle_stick(lx, ly, falling & BUTTON_A)
        except Exception:
            pass

    def _handle_stick(self, lx: int, ly: int, a_released: int) -> None:
        active = abs(lx) > DEADZONE or abs(ly) > DEADZONE
        x = int((lx / THUMB_RANGE * 0.5 + 0.5) * self._screen_w)
        y = int((1 - (ly / THUMB_RANGE * 0.5 + 0.5)) * self._screen_h)
        x = max(0, min(self._screen_w - 1, x))
        y = max(0, min(self._screen_h - 1, y))
        if active and not self._stick_touching:
            self._adb.shell(self._port, f"input motionevent DOWN {x} {y}")
            self._stick_touching = True
            self._last_x, self._last_y = x, y
        elif active and self._stick_touching:
            if abs(x - self._last_x) > 2 or abs(y - self._last_y) > 2:
                self._adb.shell(self._port, f"input motionevent MOVE {x} {y}")
                self._last_x, self._last_y = x, y
        elif not active and self._stick_touching:
            self._adb.shell(self._port, f"input motionevent UP {self._last_x} {self._last_y}")
            self._stick_touching = False
        if a_released and self._stick_touching:
            self._adb.shell(self._port, f"input motionevent UP {self._last_x} {self._last_y}")
            self._stick_touching = False

"""轻量 RFB(VNC) 客户端：连接 QEMU 内置 VNC 服务器，RAW 编码收帧。

用于 GUI 实例显示窗口：多窗口并行显示、窗口自由缩放、全屏切换、
截图（帧缓存）、指针 / 按键事件注入（键鼠触摸映射）。
"""
import struct
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
from PySide6.QtGui import QImage, QPainter

PROTOCOL_VERSION = b"RFB 003.008\n"
ENC_RAW = 0
MSG_FRAMEBUFFER_UPDATE = 0
MSG_SET_COLORMAP_ENTRIES = 1
MSG_BELL = 2
MSG_SERVER_CUT_TEXT = 3
TIMEOUT_MS = 8000

# 常用按键 -> X11 keysym 映射（Qt::Key -> keysym）
_SPECIAL_KEYSYMS = {
    0x01000000: 0xFF1B,  # Escape
    0x01000001: 0xFF09,  # Tab
    0x01000002: 0xFE20,  # Backtab
    0x01000003: 0xFF08,  # Backspace
    0x01000004: 0xFF0D,  # Return
    0x01000005: 0xFF8D,  # Enter (numpad)
    0x01000006: 0xFF63,  # Insert
    0x01000007: 0xFFFF,  # Delete
    0x01000010: 0xFF50,  # Home
    0x01000011: 0xFF57,  # End
    0x01000012: 0xFF51,  # Left
    0x01000013: 0xFF52,  # Up
    0x01000014: 0xFF53,  # Right
    0x01000015: 0xFF54,  # Down
    0x01000016: 0xFF55,  # PageUp
    0x01000017: 0xFF56,  # PageDown
    0x01000020: 0xFFE1,  # Shift
    0x01000021: 0xFFE3,  # Control
    0x01000022: 0xFFE7,  # Meta
    0x01000023: 0xFFE9,  # Alt
    0x01000024: 0xFFE7,  # AltGr -> Meta_R
    0x01000025: 0xFFE5,  # CapsLock
}

# 指针按键掩码：左 1 / 中 2 / 右 4 / 滚轮上 8 / 滚轮下 16
POINTER_LEFT = 0x01
POINTER_MIDDLE = 0x02
POINTER_RIGHT = 0x04
POINTER_WHEEL_UP = 0x08
POINTER_WHEEL_DOWN = 0x10


def qt_key_to_keysym(key, text: str) -> int:
    """Qt 键值 -> X11 keysym（可打印字符用文本编码）。"""
    value = int(key)
    if text and len(text) == 1:
        code = ord(text)
        if 0x20 <= code <= 0x7E:
            return code
    if value in _SPECIAL_KEYSYMS:
        return _SPECIAL_KEYSYMS[value]
    if 0x01000030 <= value <= 0x0100003B:      # F1 - F12
        return 0xFFBE + (value - 0x01000030)
    if value == 0x20:                            # Space
        return 0x20
    if 0x30 <= value <= 0x39:                    # 0-9
        return value
    if 0x41 <= value <= 0x5A:                    # A-Z
        return value
    return 0


class VncClient(QObject):
    """RFB 客户端（协议版本 003.008，无密码连接 QEMU VNC，RAW 编码）。"""

    connected = Signal()
    disconnected = Signal()
    protocol_error = Signal(str)
    frame_updated = Signal()
    size_changed = Signal(int, int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._sock = QTcpSocket(self)
        self._sock.readyRead.connect(self._on_ready)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.errorOccurred.connect(self._on_error)
        self._buf = b""
        self._state = "closed"
        self._fb: Optional[QImage] = None
        self._desktop_name = ""
        self._timer = QTimer(self)  # 握手超时
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._incremental_pending = False

    # ------------------------------------------------------------- state
    @property
    def is_connected(self) -> bool:
        return self._state == "running" or self._state == "handshake"

    @property
    def framebuffer(self) -> Optional[QImage]:
        return self._fb

    @property
    def desktop_name(self) -> str:
        return self._desktop_name

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------- connect
    def connect_to(self, host: str, port: int) -> None:
        self.close()
        self._state = "connecting"
        self._buf = b""
        self._timer.start(TIMEOUT_MS)
        self._sock.connectToHost(host, port)

    def close(self) -> None:
        self._timer.stop()
        if self._sock.state() != QAbstractSocket.SocketState.UnconnectedState:
            try:
                self._sock.abort()
            except Exception:
                pass
        self._state = "closed"

    # ------------------------------------------------------------- slots
    def _on_disconnected(self) -> None:
        self._timer.stop()
        self._state = "closed"
        self.disconnected.emit()

    def _on_error(self, _error) -> None:
        self._timer.stop()
        self._state = "closed"
        self.protocol_error.emit("err_vnc_connect_failed")

    def _on_timeout(self) -> None:
        if self._state != "running":
            self._state = "closed"
            try:
                self._sock.abort()
            except Exception:
                pass
            self.protocol_error.emit("err_vnc_timeout")

    def _on_ready(self) -> None:
        self._buf += bytes(self._sock.readAll())
        try:
            self._consume()
        except (struct.error, ValueError):
            self._state = "closed"
            self._sock.abort()
            self.protocol_error.emit("err_vnc_protocol")

    # ------------------------------------------------------------- protocol
    def _consume(self) -> None:
        progressed = True
        while progressed:
            progressed = False
            if self._state == "connecting":
                if self._sock.state() == QAbstractSocket.SocketState.ConnectedState:
                    self._sock.write(PROTOCOL_VERSION)
                    self._state = "version"
                    progressed = True
            elif self._state == "version":
                if len(self._buf) >= 12:
                    server = self._buf[:12]
                    self._buf = self._buf[12:]
                    if not server.startswith(b"RFB "):
                        raise ValueError("bad protocol version")
                    self._sock.write(PROTOCOL_VERSION)
                    self._state = "security"
                    progressed = True
            elif self._state == "security":
                if len(self._buf) >= 1:
                    n_types = self._buf[0]
                    if n_types == 0:
                        raise ValueError("no security types")
                    if len(self._buf) >= 1 + n_types:
                        types = self._buf[1:1 + n_types]
                        self._buf = self._buf[1 + n_types:]
                        if 1 in types:  # None（QEMU VNC 默认无密码）
                            self._sock.write(b"\x01")
                            self._state = "secresult"
                        else:
                            raise ValueError("password required")
                        progressed = True
            elif self._state == "secresult":
                if len(self._buf) >= 4:
                    (result,) = struct.unpack(">I", self._buf[:4])
                    self._buf = self._buf[4:]
                    if result != 0:
                        raise ValueError("security handshake failed")
                    self._sock.write(b"\x01")  # ClientInit: shared
                    self._state = "serverinit"
                    progressed = True
            elif self._state == "serverinit":
                if len(self._buf) >= 24 + 4:
                    width, height = struct.unpack(">HH", self._buf[0:4])
                    # pixel format（16 字节）跳过
                    (name_len,) = struct.unpack(">I", self._buf[20:24])
                    if len(self._buf) >= 24 + name_len:
                        self._desktop_name = self._buf[24:24 + name_len].decode(
                            "utf-8", errors="replace")
                        self._buf = self._buf[24 + name_len:]
                        self._fb = QImage(width, height,
                                          QImage.Format.Format_RGB32)
                        self._fb.fill(0xFF1E1E2F)
                        self._send_set_pixel_format()
                        self._send_set_encodings()
                        self._request_update(incremental=0)
                        self._state = "running"
                        self.connected.emit()
                        self.size_changed.emit(width, height)
                        progressed = True
            elif self._state == "running":
                progressed = self._consume_messages()

    def _consume_messages(self) -> bool:
        """处理服务器消息；处理了至少一条返回 True。"""
        handled = False
        while self._state == "running":
            if len(self._buf) < 4:
                return handled
            msg_type = self._buf[0]
            if msg_type == MSG_FRAMEBUFFER_UPDATE:
                if len(self._buf) < 4:
                    return handled
                (n_rects,) = struct.unpack(">H", self._buf[2:4])
                offset = 4
                rects_done = 0
                incomplete = False
                for _ in range(n_rects):
                    if len(self._buf) < offset + 12:
                        incomplete = True
                        break
                    x, y, w, h = struct.unpack(">HHHH", self._buf[offset:offset + 8])
                    (enc,) = struct.unpack(">i", self._buf[offset + 8:offset + 12])
                    if enc != ENC_RAW:
                        raise ValueError(f"unsupported encoding {enc}")
                    data_len = w * h * 4
                    if len(self._buf) < offset + 12 + data_len:
                        incomplete = True
                        break
                    data = self._buf[offset + 12:offset + 12 + data_len]
                    self._blit(x, y, w, h, data)
                    offset += 12 + data_len
                    rects_done += 1
                if incomplete:
                    return handled
                self._buf = self._buf[offset:]
                handled = True
                self.frame_updated.emit()
                self._request_update(incremental=1)
            elif msg_type == MSG_SET_COLORMAP_ENTRIES:
                if len(self._buf) < 6:
                    return handled
                (n_colors,) = struct.unpack(">H", self._buf[4:6])
                total = 6 + n_colors * 6
                if len(self._buf) < total:
                    return handled
                self._buf = self._buf[total:]
                handled = True
            elif msg_type == MSG_BELL:
                self._buf = self._buf[1:]
                handled = True
            elif msg_type == MSG_SERVER_CUT_TEXT:
                if len(self._buf) < 8:
                    return handled
                (text_len,) = struct.unpack(">I", self._buf[4:8])
                if len(self._buf) < 8 + text_len:
                    return handled
                self._buf = self._buf[8 + text_len:]
                handled = True
            else:
                raise ValueError(f"unknown message type {msg_type}")
        return handled

    # ------------------------------------------------------------- helpers
    def _blit(self, x: int, y: int, w: int, h: int, data: bytes) -> None:
        if self._fb is None or w <= 0 or h <= 0:
            return
        if len(data) != w * h * 4:
            return
        ba = bytearray(data)
        ba[3::4] = b"\xff" * (w * h)
        tile = QImage(bytes(ba), w, h, QImage.Format.Format_RGB32)
        if tile.isNull():
            return
        painter = QPainter(self._fb)
        painter.drawImage(x, y, tile)
        painter.end()

    def _send_set_pixel_format(self) -> None:
        # 32bpp / depth24 / 小端 / 真彩 RGB（shifts 16/8/0，与 QImage RGB32 一致）
        fmt = struct.pack(">BBBBHHHBBB3x",
                          32, 24, 0, 1,
                          0xFF, 0xFF, 0xFF,
                          16, 8, 0)
        self._sock.write(struct.pack(">B3x", 0) + fmt)

    def _send_set_encodings(self) -> None:
        self._sock.write(struct.pack(">BBh", 2, 0, 1) + struct.pack(">i", ENC_RAW))

    def _request_update(self, incremental: int = 1) -> None:
        if self._fb is None:
            return
        self._sock.write(struct.pack(
            ">BBHHHH", 3, incremental, 0, 0,
            self._fb.width(), self._fb.height()))

    # ------------------------------------------------------------- input
    def send_pointer_event(self, x: int, y: int, mask: int) -> None:
        if self._state != "running":
            return
        self._sock.write(struct.pack(">BBHH", 5, mask & 0xFF, x, y))

    def send_key_event(self, keysym: int, down: bool) -> None:
        if self._state != "running":
            return
        self._sock.write(struct.pack(">BB2xI", 4, 1 if down else 0, keysym))

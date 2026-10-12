"""实例显示窗口：多窗口并行显示、窗口自由缩放、全屏切换、截图录屏、
剪贴板双向同步、键位映射 / 手柄、拖拽 APK 安装。"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QToolBar, QVBoxLayout, QWidget,
)

from core.guest_agent import GuestAgentClient
from gui.i18n import bind, tr
from gui.vnc_client import (
    POINTER_LEFT, POINTER_MIDDLE, POINTER_RIGHT, POINTER_WHEEL_DOWN,
    POINTER_WHEEL_UP, VncClient, qt_key_to_keysym,
)
from gui.widgets import AsyncRunner
from tools import clipboard as clipboard_tool
from tools.keymap import KeyMappingProfile, apply_key
from tools.recorder import ScreenRecorder
from tools.screenshot import capture_screenshot

ZOOM_FIT = 0
ZOOM_STEPS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

# Qt 按键 -> 宿主键名（键位映射档案使用）
_QT_SPECIAL_NAMES = {
    Qt.Key.Key_Space: "SPACE", Qt.Key.Key_Return: "ENTER", Qt.Key.Key_Enter: "ENTER",
    Qt.Key.Key_Tab: "TAB", Qt.Key.Key_Backtab: "TAB", Qt.Key.Key_Backspace: "BACKSPACE",
    Qt.Key.Key_Escape: "ESC", Qt.Key.Key_Delete: "DEL", Qt.Key.Key_Insert: "INS",
    Qt.Key.Key_Home: "HOME", Qt.Key.Key_End: "END",
    Qt.Key.Key_PageUp: "PGUP", Qt.Key.Key_PageDown: "PGDN",
    Qt.Key.Key_Left: "LEFT", Qt.Key.Key_Up: "UP",
    Qt.Key.Key_Right: "RIGHT", Qt.Key.Key_Down: "DOWN",
    Qt.Key.Key_Shift: "SHIFT", Qt.Key.Key_Control: "CTRL",
    Qt.Key.Key_Alt: "ALT", Qt.Key.Key_Meta: "META", Qt.Key.Key_CapsLock: "CAPS",
}


def host_key_name(key, text: str) -> str:
    """宿主按键名（键位映射键，如 W / SPACE / F1 / UP）。"""
    if text and len(text) == 1 and text.isprintable() and not text.isspace():
        return text.upper()
    if key in _QT_SPECIAL_NAMES:
        return _QT_SPECIAL_NAMES[key]
    value = int(key)
    if 0x01000030 <= value <= 0x0100003B:
        return f"F{value - 0x01000030 + 1}"
    if 0x30 <= value <= 0x39 or 0x41 <= value <= 0x5A:
        return chr(value)
    return ""


class VncDisplayWidget(QWidget):
    """VNC 帧渲染控件：缩放显示 + 指针/按键事件注入。"""

    def __init__(self, vnc: VncClient, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vnc = vnc
        self._zoom = ZOOM_FIT
        self._key_handler = None  # 宿主键 -> 虚拟机映射动作回调
        self.setMinimumSize(320, 480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._buttons = 0
        vnc.frame_updated.connect(self.update)
        vnc.size_changed.connect(self.update)

    def set_key_handler(self, handler) -> None:
        """注册键位映射处理器：返回 True 表示按键已被映射消费。"""
        self._key_handler = handler

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self.update()

    def _scale_rect(self):
        fb = self._vnc.framebuffer
        if fb is None or fb.isNull() or fb.width() == 0 or fb.height() == 0:
            return None
        fw, fh = fb.width(), fb.height()
        if self._zoom == ZOOM_FIT:
            scale = min(self.width() / fw, self.height() / fh)
        else:
            scale = self._zoom
        dw, dh = int(fw * scale), int(fh * scale)
        ox, oy = (self.width() - dw) // 2, (self.height() - dh) // 2
        return ox, oy, scale, dw, dh

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self._scale_rect()
        fb = self._vnc.framebuffer
        if rect is None or fb is None or fb.isNull():
            painter.fillRect(self.rect(), 0xFF121212)
            painter.end()
            return
        ox, oy, _scale, dw, dh = rect
        painter.fillRect(self.rect(), 0xFF121212)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRect(ox, oy, dw, dh)
        source = QRect(0, 0, fb.width(), fb.height())
        painter.drawImage(target, fb, source)
        painter.end()

    def _to_guest(self, pos):
        rect = self._scale_rect()
        if rect is None:
            return None
        ox, oy, scale, dw, dh = rect
        gx = (pos.x() - ox) / scale if scale else 0
        gy = (pos.y() - oy) / scale if scale else 0
        gx = max(0, min(dw / scale - 1, gx))
        gy = max(0, min(dh / scale - 1, gy))
        return int(gx), int(gy)

    # ------------------------------------------------------------- pointer
    def _mask_for_buttons(self, buttons) -> int:
        mask = 0
        if buttons & Qt.MouseButton.LeftButton:
            mask |= POINTER_LEFT
        if buttons & Qt.MouseButton.MiddleButton:
            mask |= POINTER_MIDDLE
        if buttons & Qt.MouseButton.RightButton:
            mask |= POINTER_RIGHT
        return mask

    def mousePressEvent(self, event) -> None:  # noqa: N802
        point = self._to_guest(event.position())
        if point:
            self._buttons = self._mask_for_buttons(event.buttons())
            self._vnc.send_pointer_event(point[0], point[1], self._buttons)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        point = self._to_guest(event.position())
        if point:
            self._buttons = self._mask_for_buttons(event.buttons())
            self._vnc.send_pointer_event(point[0], point[1], self._buttons)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._buttons or event.buttons():
            point = self._to_guest(event.position())
            if point:
                self._mask_for_buttons(event.buttons())
                self._vnc.send_pointer_event(
                    point[0], point[1],
                    self._mask_for_buttons(event.buttons()))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        point = self._to_guest(event.position())
        if point:
            mask = self._buttons or POINTER_LEFT
            wheel = POINTER_WHEEL_UP if event.angleDelta().y() > 0 else POINTER_WHEEL_DOWN
            self._vnc.send_pointer_event(point[0], point[1], mask | wheel)
            self._vnc.send_pointer_event(point[0], point[1], mask)

    # ------------------------------------------------------------- key
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._key_handler is not None:
            name = host_key_name(event.key(), event.text())
            if name:
                try:
                    if self._key_handler(name):
                        return  # 已被键位映射消费
                except Exception:
                    pass
        keysym = qt_key_to_keysym(event.key(), event.text())
        if keysym:
            self._vnc.send_key_event(keysym, True)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        keysym = qt_key_to_keysym(event.key(), event.text())
        if keysym:
            self._vnc.send_key_event(keysym, False)


class DisplayWindow(QMainWindow):
    """单实例显示窗口（多开时每实例一窗口，并行显示）。"""

    window_closed = Signal(str)

    def __init__(self, service, instance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._inst = instance
        self._vnc = VncClient(self)
        self._display = VncDisplayWidget(self._vnc)
        self._recorder = ScreenRecorder(service.adb)
        self._keymap: Optional[KeyMappingProfile] = None
        self._keymap_enabled = False
        self._agent = GuestAgentClient(port=instance.config.agent_port)

        self.setWindowTitle(f"{instance.name} - {tr('app_title')}")
        self.setAcceptDrops(True)
        self.resize(420, 800)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._display)
        self.setCentralWidget(central)

        self._build_toolbar()
        self._build_status()
        self._display.set_key_handler(self._handle_host_key)

        self._vnc.connected.connect(self._on_connected)
        self._vnc.disconnected.connect(self._on_disconnected)
        self._vnc.protocol_error.connect(self._on_error)
        self._vnc.frame_updated.connect(self._on_frame)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(3000)
        self._reconnect_timer.timeout.connect(self._try_connect)
        self._reconnect_timer.start()
        self._try_connect()

    # ------------------------------------------------------------- UI
    def _build_toolbar(self) -> None:
        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)

        self._fullscreen_btn = QPushButton()
        bind(self._fullscreen_btn, "btn_fullscreen")
        self._fullscreen_btn.clicked.connect(self.toggle_fullscreen)

        self._zoom_combo = QComboBox()
        self._zoom_combo.setMinimumWidth(110)
        for zoom in ZOOM_STEPS:
            self._zoom_combo.addItem(f"{int(zoom * 100)}%", zoom)
        self._zoom_combo.insertItem(0, tr("zoom_fit"), ZOOM_FIT)
        self._zoom_combo.setCurrentIndex(0)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom)

        self._screenshot_btn = QPushButton()
        bind(self._screenshot_btn, "btn_screenshot")
        self._screenshot_btn.clicked.connect(self.do_screenshot)

        self._record_btn = QPushButton()
        bind(self._record_btn, "btn_record")
        self._record_btn.clicked.connect(self.toggle_record)

        self._clipboard_btn = QPushButton()
        bind(self._clipboard_btn, "btn_clipboard_sync")
        self._clipboard_btn.clicked.connect(self.sync_clipboard)

        self._keymap_btn = QPushButton()
        bind(self._keymap_btn, "btn_keymap_toggle")
        self._keymap_btn.setCheckable(True)
        self._keymap_btn.toggled.connect(self._on_keymap_toggle)

        self._gamepad_btn = QPushButton()
        bind(self._gamepad_btn, "btn_gamepad_toggle")
        self._gamepad_btn.setCheckable(True)
        self._gamepad_btn.toggled.connect(self._on_gamepad_toggle)

        for w in (self._fullscreen_btn, self._zoom_combo, self._screenshot_btn,
                  self._record_btn, self._clipboard_btn, self._keymap_btn,
                  self._gamepad_btn):
            bar.addWidget(w)

    def _build_status(self) -> None:
        self._status_label = QLabel(tr("vnc_status_connecting"))
        self.statusBar().addWidget(self._status_label)
        self._size_label = QLabel("")
        self.statusBar().addPermanentWidget(self._size_label)
        self._adb_label = QLabel(f"adb connect 127.0.0.1:{self._inst.config.adb_port}")
        self.statusBar().addPermanentWidget(self._adb_label)

    # ------------------------------------------------------------- connect
    def _try_connect(self) -> None:
        if self._vnc.state == "closed":
            self._status_label.setText(tr("vnc_status_connecting"))
            self._vnc.connect_to("127.0.0.1", self._inst.vnc_port)

    def _on_connected(self) -> None:
        fb = self._vnc.framebuffer
        if fb:
            self._size_label.setText(f"{fb.width()}x{fb.height()}")
        self._status_label.setText(tr("vnc_status_connected"))
        self._reconnect_timer.stop()

    def _on_disconnected(self) -> None:
        self._status_label.setText(tr("vnc_status_disconnected"))
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def _on_error(self, key: str) -> None:
        self._status_label.setText(tr(key))
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def _on_frame(self) -> None:
        pass

    def reconnect(self) -> None:
        self._vnc.close()
        self._try_connect()

    # ------------------------------------------------------------- actions
    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_zoom(self, _index: int) -> None:
        zoom = self._zoom_combo.currentData()
        self._display.set_zoom(float(zoom) if zoom is not None else ZOOM_FIT)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def do_screenshot(self) -> None:
        def job():
            return capture_screenshot(
                self._service.adb, self._inst.config.adb_port, self._inst.name)

        def done(path: Path):
            QMessageBox.information(
                self, tr("msg_screenshot_saved_title"),
                tr("msg_screenshot_saved", path=str(path)))

        AsyncRunner(self, tr("msg_working"), job, done).start()

    def toggle_record(self) -> None:
        if self._recorder.recording:
            def job():
                return self._recorder.stop()

            def done(path: Path):
                QMessageBox.information(
                    self, tr("msg_record_saved_title"),
                    tr("msg_record_saved", path=str(path)))

            self._record_btn.setText(tr("btn_record"))
            AsyncRunner(self, tr("msg_working"), job, done).start()
        else:
            try:
                self._recorder.start(self._inst.config.adb_port, self._inst.name)
                self._record_btn.setText(tr("btn_stop_record"))
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("msg_error"),
                                    tr(getattr(exc, "args", [""])[0] or "err_unknown"))


    def sync_clipboard(self) -> None:
        """宿主机-虚拟机剪贴板双向同步。"""
        text = QGuiApplication.clipboard().text()
        if text:
            clipboard_tool.sync_to_guest(
                text, self._service.adb, self._inst.config.adb_port, self._agent)
        guest_text = clipboard_tool.sync_from_guest(
            self._service.adb, self._inst.config.adb_port, self._agent)
        if guest_text:
            QGuiApplication.clipboard().setText(guest_text)
        self._status_label.setText(tr("msg_clipboard_synced"))
        QTimer.singleShot(2000, lambda: self._status_label.setText(
            tr("vnc_status_connected") if self._vnc.state == "running"
            else tr("vnc_status_disconnected")))

    # ------------------------------------------------------------- keymap
    def set_keymap(self, profile: KeyMappingProfile, enabled: bool) -> None:
        self._keymap = profile
        self._keymap_enabled = enabled
        self._keymap_btn.setChecked(enabled)

    def _handle_host_key(self, key_name: str) -> bool:
        """键鼠触摸映射：宿主键 -> 虚拟机动作；未映射返回 False 走 RFB 按键注入。"""
        if not (self._keymap_enabled and self._keymap):
            return False
        try:
            return apply_key(
                self._service.adb, self._inst.config.adb_port,
                self._keymap, key_name)
        except Exception:
            return False

    def _on_keymap_toggle(self, checked: bool) -> None:
        self._keymap_enabled = checked
        if checked and self._keymap is None:
            self._keymap = KeyMappingProfile.load("default")
            if self._keymap is None:
                self._keymap = KeyMappingProfile(name="default")

    def _on_gamepad_toggle(self, checked: bool) -> None:
        from tools.gamepad import GamepadBridge
        if checked:
            if not hasattr(self, "_gamepad"):
                fb = self._vnc.framebuffer
                w = fb.width() if fb else 1280
                h = fb.height() if fb else 720
                self._gamepad = GamepadBridge(
                    self._service.adb, self._inst.config.adb_port, w, h)
            if not self._gamepad.available:
                QMessageBox.warning(self, tr("msg_error"), tr("err_gamepad_unavailable"))
                self._gamepad_btn.setChecked(False)
                return
            self._gamepad.set_enabled(True)
            if not hasattr(self, "_gamepad_timer"):
                self._gamepad_timer = QTimer(self)
                self._gamepad_timer.setInterval(33)
                self._gamepad_timer.timeout.connect(self._gamepad.tick)
            self._gamepad_timer.start()
        else:
            if hasattr(self, "_gamepad"):
                self._gamepad.set_enabled(False)
            if hasattr(self, "_gamepad_timer"):
                self._gamepad_timer.stop()

    # ------------------------------------------------------------- drag & drop APK
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and all(u.isLocalFile() and u.toLocalFile().lower().endswith(".apk")
                        for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        apks = [u.toLocalFile() for u in event.mimeData().urls()]
        if not apks:
            return
        port = self._inst.config.adb_port

        def job():
            self._service.adb.connect(port)
            for apk in apks:
                self._service.adb.install(port, apk)
            return len(apks)

        def done(count: int):
            QMessageBox.information(
                self, tr("msg_install_success_title"),
                tr("msg_install_success_count", count=count))

        AsyncRunner(self, tr("msg_installing"), job, done).start()

    # ------------------------------------------------------------- close
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._recorder.recording:
            self._recorder.stop_async()
        self._reconnect_timer.stop()
        self._vnc.close()
        if hasattr(self, "_gamepad_timer"):
            self._gamepad_timer.stop()
        self.window_closed.emit(self._inst.id)
        super().closeEvent(event)

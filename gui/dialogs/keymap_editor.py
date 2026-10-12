"""键鼠触摸映射 + 手柄映射编辑器（两个选项卡，共享动作模型）。

- 键位映射：捕获宿主按键 -> 虚拟机动作（点击 / 滑动 / 按键 / 文本）
- 手柄映射：XInput 按键 -> 虚拟机动作（保存到 gamepad.json，随显示窗口启用生效）
"""
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.i18n import bind, tr
from tools.gamepad import BUTTON_NAMES
from tools.keymap import ACTION_TYPES, InputAction, KeyMappingProfile

CAPTURE_NONE = ""


class KeymapEditorDialog(QDialog):
    def __init__(self, service, instance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._inst = instance
        self._capturing_row = -1

        self.setWindowTitle(tr("dlg_keymap_editor", name=instance.name))
        self.setMinimumSize(720, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self._tabs = QTabWidget()

        # -------------------------------------------------- 键位映射
        page_key = QWidget()
        key_layout = QVBoxLayout(page_key)

        profile_row = QHBoxLayout()
        self._profile_name = QLineEdit("default")
        name_label = QLabel(); bind(name_label, "lbl_keymap_profile")
        self._load_profiles = QComboBox()
        self._refresh_btn = QPushButton(); bind(self._refresh_btn, "btn_refresh_profiles")
        self._refresh_btn.clicked.connect(self._refresh_profiles)
        self._load_btn = QPushButton(); bind(self._load_btn, "btn_load_keymap")
        self._load_btn.clicked.connect(self._load_profile)
        self._save_btn = QPushButton(); bind(self._save_btn, "btn_save_keymap")
        self._save_btn.clicked.connect(self._save_profile)
        profile_row.addWidget(name_label)
        profile_row.addWidget(self._profile_name, 1)
        profile_row.addWidget(self._load_profiles, 1)
        profile_row.addWidget(self._refresh_btn)
        profile_row.addWidget(self._load_btn)
        profile_row.addWidget(self._save_btn)
        key_layout.addLayout(profile_row)

        self._key_table = QTableWidget(0, 6)
        self._key_table.setHorizontalHeaderLabels([
            tr("col_host_key"), tr("col_action_type"),
            "X", "Y", "X2 / Y2", tr("col_keycode_text"),
        ])
        self._key_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        key_layout.addWidget(self._key_table, 1)

        key_btns = QHBoxLayout()
        self._add_key_btn = QPushButton(); bind(self._add_key_btn, "btn_add_binding")
        self._add_key_btn.clicked.connect(self._add_key_row)
        self._del_key_btn = QPushButton(); bind(self._del_key_btn, "btn_del_step")
        self._del_key_btn.clicked.connect(self._del_key_row)
        self._apply_keymap_btn = QPushButton(); bind(self._apply_keymap_btn, "btn_apply_keymap")
        self._apply_keymap_btn.setObjectName("primary")
        self._apply_keymap_btn.clicked.connect(self.accept)
        for b in (self._add_key_btn, self._del_key_btn, self._apply_keymap_btn):
            key_btns.addWidget(b)
        key_btns.addStretch(1)
        key_layout.addLayout(key_btns)
        self._tabs.addTab(page_key, tr("tab_keymap"))

        # -------------------------------------------------- 手柄映射
        page_pad = QWidget()
        pad_layout = QVBoxLayout(page_pad)
        hint = QLabel(); bind(hint, "lbl_gamepad_hint")
        pad_layout.addWidget(hint)
        self._pad_table = QTableWidget(0, 6)
        self._pad_table.setHorizontalHeaderLabels([
            tr("col_gamepad_button"), tr("col_action_type"),
            "X", "Y", "X2 / Y2", tr("col_keycode_text"),
        ])
        self._pad_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        pad_layout.addWidget(self._pad_table, 1)
        pad_btns = QHBoxLayout()
        self._add_pad_btn = QPushButton(); bind(self._add_pad_btn, "btn_add_binding")
        self._add_pad_btn.clicked.connect(self._add_pad_row)
        self._del_pad_btn = QPushButton(); bind(self._del_pad_btn, "btn_del_step")
        self._del_pad_btn.clicked.connect(lambda: self._del_row(self._pad_table))
        self._save_pad_btn = QPushButton(); bind(self._save_pad_btn, "btn_save_gamepad")
        self._save_pad_btn.setObjectName("primary")
        self._save_pad_btn.clicked.connect(self._save_pad)
        for b in (self._add_pad_btn, self._del_pad_btn, self._save_pad_btn):
            pad_btns.addWidget(b)
        pad_btns.addStretch(1)
        pad_layout.addLayout(pad_btns)
        self._tabs.addTab(page_pad, tr("tab_gamepad"))

        root.addWidget(self._tabs)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("btn_close"))
        close.clicked.connect(self.reject)
        root.addWidget(close)

        self._refresh_profiles()
        self._load_default()
        self._load_pad()

    # ------------------------------------------------------------- profiles
    def _refresh_profiles(self) -> None:
        self._load_profiles.clear()
        for name in KeyMappingProfile.list_profiles():
            self._load_profiles.addItem(name.replace(".json", ""), name)

    def _load_default(self) -> None:
        profile = KeyMappingProfile.load("default") or KeyMappingProfile(name="default")
        self._profile_name.setText(profile.name)
        self._key_table.setRowCount(0)
        for key, action in profile.bindings.items():
            self._add_key_row(key, action)

    def _load_profile(self) -> None:
        name = self._load_profiles.currentData() or "default"
        profile = KeyMappingProfile.load(name.replace(".json", ""))
        if profile is None:
            profile = KeyMappingProfile.load("default") or KeyMappingProfile(name="default")
        self._profile_name.setText(profile.name)
        self._key_table.setRowCount(0)
        for key, action in profile.bindings.items():
            self._add_key_row(key, action)

    def _save_profile(self) -> None:
        profile = KeyMappingProfile(name=self._profile_name.text().strip() or "default")
        profile.bindings = self._collect_keymap()
        path = profile.save()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, tr("msg_keymap_saved_title"),
                                tr("msg_keymap_saved", path=str(path)))

    def collect_profile(self) -> KeyMappingProfile:
        profile = KeyMappingProfile(
            name=self._profile_name.text().strip() or "default",
            bindings=self._collect_keymap(),
        )
        if not profile.bindings:
            loaded = KeyMappingProfile.load(profile.name)
            if loaded:
                profile = loaded
        return profile

    # ------------------------------------------------------------- key rows
    def _add_key_row(self, key: str = "", action: Optional[InputAction] = None) -> None:
        action = action or InputAction()
        row = self._key_table.rowCount()
        self._key_table.insertRow(row)
        capture = QPushButton(key or tr("btn_capture"))
        capture.clicked.connect(lambda: self._capture(row))
        self._key_table.setCellWidget(row, 0, capture)
        self._add_action_cells(self._key_table, row, action)

    def _capture(self, row: int) -> None:
        self._capturing_row = row
        btn = self._key_table.cellWidget(row, 0)
        if btn:
            btn.setText(tr("msg_capturing"))
        self._key_table.setFocus()

    def _del_key_row(self) -> None:
        self._del_row(self._key_table)

    @staticmethod
    def _del_row(table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    # ------------------------------------------------------------- pad rows
    def _add_pad_row(self, button: str = "", action: Optional[InputAction] = None) -> None:
        action = action or InputAction()
        row = self._pad_table.rowCount()
        self._pad_table.insertRow(row)
        combo = QComboBox()
        for name in BUTTON_NAMES:
            combo.addItem(name, name)
        if button:
            combo.setCurrentIndex(combo.findData(button))
        self._pad_table.setCellWidget(row, 0, combo)
        self._add_action_cells(self._pad_table, row, action)

    def _save_pad(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from tools.gamepad import GamepadBridge
        mapping = {}
        for row in range(self._pad_table.rowCount()):
            combo = self._pad_table.cellWidget(row, 0)
            if combo is None:
                continue
            button = combo.currentData()
            action = self._row_action(self._pad_table, row)
            if button and action:
                mapping[button] = action
        bridge = GamepadBridge(self._service.adb, self._inst.config.adb_port)
        bridge.set_mapping(mapping)
        QMessageBox.information(self, tr("msg_gamepad_saved_title"),
                                tr("msg_gamepad_saved"))

    def _load_pad(self) -> None:
        from tools.gamepad import GamepadBridge
        bridge = GamepadBridge(self._service.adb, self._inst.config.adb_port)
        for button, action in bridge.load_mapping().items():
            self._add_pad_row(button, action)

    # ------------------------------------------------------------- common
    def _add_action_cells(self, table: QTableWidget, row: int, action: InputAction) -> None:
        combo = QComboBox()
        for t in ACTION_TYPES:
            combo.addItem(tr(f"action_{t}"), t)
        combo.setCurrentIndex(combo.findData(action.type))
        table.setCellWidget(row, 1, combo)
        table.setItem(row, 2, QTableWidgetItem(str(action.x)))
        table.setItem(row, 3, QTableWidgetItem(str(action.y)))
        table.setItem(row, 4, QTableWidgetItem(
            f"{action.x2},{action.y2}" if action.type == "swipe" else "-"))
        table.setItem(row, 5, QTableWidgetItem(
            str(action.keycode) if action.type == "key"
            else (action.text if action.type == "text" else "-")))

    def _row_action(self, table: QTableWidget, row: int) -> Optional[InputAction]:
        combo = table.cellWidget(row, 1)
        if combo is None:
            return None
        action_type = combo.currentData() or "tap"

        def num(col, default=0):
            item = table.item(row, col)
            try:
                return int(float(item.text())) if item else default
            except (ValueError, AttributeError):
                return default

        action = InputAction(type=action_type, x=num(2), y=num(3),
                             x2=num(4), duration_ms=300, keycode=0, text="")
        if action_type == "swipe":
            xy2 = (table.item(row, 4).text() if table.item(row, 4) else "0,0").split(",")
            try:
                action.x2, action.y2 = int(float(xy2[0])), int(float(xy2[1]))
            except (ValueError, IndexError):
                pass
        if action_type == "key":
            action.keycode = num(5)
        elif action_type == "text":
            action.text = table.item(row, 5).text() if table.item(row, 5) else ""
        try:
            action.validate()
        except ValueError:
            return None
        return action

    def _collect_keymap(self) -> dict:
        bindings = {}
        for row in range(self._key_table.rowCount()):
            capture = self._key_table.cellWidget(row, 0)
            if capture is None:
                continue
            key = capture.text()
            if not key or key == tr("btn_capture") or key == tr("msg_capturing"):
                continue
            action = self._row_action(self._key_table, row)
            if action is not None:
                bindings[key] = action
        return bindings

    # ------------------------------------------------------------- capture
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._capturing_row >= 0:
            row = self._capturing_row
            self._capturing_row = -1
            key = event.text()
            if key and len(key) == 1 and key.isprintable() and not key.isspace():
                name = key.upper()
            else:
                special = {
                    Qt.Key.Key_Space: "SPACE", Qt.Key.Key_Return: "ENTER",
                    Qt.Key.Key_Enter: "ENTER", Qt.Key.Key_Tab: "TAB",
                    Qt.Key.Key_Backspace: "BACKSPACE", Qt.Key.Key_Escape: "ESC",
                    Qt.Key.Key_Delete: "DEL", Qt.Key.Key_Insert: "INS",
                    Qt.Key.Key_Home: "HOME", Qt.Key.Key_End: "END",
                    Qt.Key.Key_PageUp: "PGUP", Qt.Key.Key_PageDown: "PGDN",
                    Qt.Key.Key_Left: "LEFT", Qt.Key.Key_Up: "UP",
                    Qt.Key.Key_Right: "RIGHT", Qt.Key.Key_Down: "DOWN",
                    Qt.Key.Key_Shift: "SHIFT", Qt.Key.Key_Control: "CTRL",
                    Qt.Key.Key_Alt: "ALT", Qt.Key.Key_Meta: "META",
                }
                name = special.get(event.key(), "")
                value = int(event.key())
                if not name and 0x01000030 <= value <= 0x0100003B:
                    name = f"F{value - 0x01000030 + 1}"
            btn = self._key_table.cellWidget(row, 0)
            if btn and name:
                btn.setText(name)
            return
        super().keyPressEvent(event)

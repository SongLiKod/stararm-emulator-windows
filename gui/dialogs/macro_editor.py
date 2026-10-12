"""自定义宏脚本编辑器：步骤编排 / 保存 / 载入 / 导入导出 / 运行 / 取消。"""
import json
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.i18n import bind, tr
from tools.macro import Macro, MacroRunner, MacroStep

STEP_TYPES = ("tap", "swipe", "key", "text", "sleep")


class MacroEditorDialog(QDialog):
    def __init__(self, service, instance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._inst = instance
        self._cancel = threading.Event()

        self.setWindowTitle(tr("dlg_macro_editor", name=instance.name))
        self.setMinimumSize(760, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        top = QFormLayout()
        self._macro_name = QLineEdit("macro-1")
        name_label = QLabel(); bind(name_label, "lbl_macro_name")
        top.addRow(name_label, self._macro_name)
        self._profiles = QComboBox()
        self._refresh_btn = QPushButton()
        bind(self._refresh_btn, "btn_refresh_profiles")
        self._refresh_btn.clicked.connect(self._refresh_profiles)
        self._load_btn = QPushButton()
        bind(self._load_btn, "btn_load_macro")
        self._load_btn.clicked.connect(self._load)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self._profiles, 1)
        profile_row.addWidget(self._refresh_btn)
        profile_row.addWidget(self._load_btn)
        profile_label = QLabel(); bind(profile_label, "lbl_macro_list")
        top.addRow(profile_label, profile_row)
        self._loops = QSpinBox(); self._loops.setRange(1, 9999); self._loops.setValue(1)
        loops_label = QLabel(); bind(loops_label, "lbl_macro_loops")
        top.addRow(loops_label, self._loops)
        root.addLayout(top)

        # 步骤表
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            tr("col_step_type"), tr("col_x"), tr("col_y"),
            tr("col_x2"), tr("col_y2"), tr("col_duration"),
            tr("col_keycode_text"), tr("col_seconds"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, 1)

        # 新增行参数
        params = QFormLayout()
        self._step_type = QComboBox()
        for t in STEP_TYPES:
            self._step_type.addItem(tr(f"step_{t}"), t)
        type_label = QLabel(); bind(type_label, "lbl_step_type")
        params.addRow(type_label, self._step_type)
        self._px = QSpinBox(); self._px.setRange(0, 7680); self._px.setValue(500)
        self._py = QSpinBox(); self._py.setRange(0, 4320); self._py.setValue(500)
        self._px2 = QSpinBox(); self._px2.setRange(0, 7680); self._px2.setValue(700)
        self._py2 = QSpinBox(); self._py2.setRange(0, 4320); self._py2.setValue(500)
        self._pdur = QSpinBox(); self._pdur.setRange(50, 10000); self._pdur.setValue(300)
        self._pkey = QSpinBox(); self._pkey.setRange(0, 999)
        self._ptext = QLineEdit()
        self._psecs = QDoubleSpinBox(); self._psecs.setRange(0, 60); self._psecs.setValue(0.5)
        self._psecs.setDecimals(2)
        xy_row = QHBoxLayout()
        for lbl, w in (("X", self._px), ("Y", self._py),
                       ("X2", self._px2), ("Y2", self._py2),
                       ("ms", self._pdur)):
            xy_row.addWidget(QLabel(lbl))
            xy_row.addWidget(w)
        params.addRow(xy_row)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("key"))
        key_row.addWidget(self._pkey)
        key_row.addWidget(QLabel("text"))
        key_row.addWidget(self._ptext)
        params.addRow(key_row)
        secs_row = QHBoxLayout()
        secs_row.addWidget(QLabel(tr("col_seconds")))
        secs_row.addWidget(self._psecs)
        params.addRow(secs_row)
        root.addLayout(params)

        # 按钮区
        btns = QHBoxLayout()
        self._add_btn = QPushButton(); bind(self._add_btn, "btn_add_step")
        self._add_btn.clicked.connect(self._add_step)
        self._del_btn = QPushButton(); bind(self._del_btn, "btn_del_step")
        self._del_btn.clicked.connect(self._del_step)
        self._up_btn = QPushButton(); bind(self._up_btn, "btn_move_up")
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn = QPushButton(); bind(self._down_btn, "btn_move_down")
        self._down_btn.clicked.connect(lambda: self._move(1))
        self._save_btn = QPushButton(); bind(self._save_btn, "btn_save_macro")
        self._save_btn.clicked.connect(self._save)
        self._export_btn = QPushButton(); bind(self._export_btn, "btn_export_macro")
        self._export_btn.clicked.connect(self._export)
        self._import_btn = QPushButton(); bind(self._import_btn, "btn_import_macro")
        self._import_btn.clicked.connect(self._import)
        self._run_btn = QPushButton(); bind(self._run_btn, "btn_run_macro")
        self._run_btn.setObjectName("primary")
        self._run_btn.clicked.connect(self._run)
        self._cancel_btn = QPushButton(); bind(self._cancel_btn, "btn_cancel_macro")
        self._cancel_btn.clicked.connect(self._cancel_macro)
        for b in (self._add_btn, self._del_btn, self._up_btn, self._down_btn,
                  self._save_btn, self._export_btn, self._import_btn,
                  self._run_btn, self._cancel_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("btn_close"))
        close.clicked.connect(self.reject)
        root.addWidget(close)

        self._refresh_profiles()

    # ------------------------------------------------------------- table
    def _add_step(self) -> None:
        step = MacroStep(
            type=self._step_type.currentData() or "tap",
            x=self._px.value(), y=self._py.value(),
            x2=self._px2.value(), y2=self._py2.value(),
            duration_ms=self._pdur.value(), keycode=self._pkey.value(),
            text=self._ptext.text(), seconds=self._psecs.value(),
        )
        self._append_row(step)

    def _append_row(self, step: MacroStep) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        combo = QComboBox()
        for t in STEP_TYPES:
            combo.addItem(tr(f"step_{t}"), t)
        combo.setCurrentIndex(combo.findData(step.type))
        self._table.setCellWidget(row, 0, combo)
        values = [step.x, step.y, step.x2, step.y2, step.duration_ms,
                  step.keycode if step.keycode else step.text, step.seconds]
        for col, value in enumerate(values, start=1):
            self._table.setItem(row, col, QTableWidgetItem(str(value)))

    def _collect(self) -> Macro:
        macro = Macro(
            name=self._macro_name.text().strip() or "macro",
            loop_count=self._loops.value(),
        )
        for row in range(self._table.rowCount()):
            combo = self._table.cellWidget(row, 0)
            step_type = combo.currentData() if combo else "tap"
            def num(col, default=0):
                item = self._table.item(row, col)
                try:
                    return int(float(item.text())) if item else default
                except (ValueError, AttributeError):
                    return default
            step = MacroStep(
                type=step_type,
                x=num(1), y=num(2), x2=num(3), y2=num(4),
                duration_ms=num(5, 300),
                keycode=num(6) if step_type == "key" else 0,
                text=self._table.item(row, 6).text() if step_type == "text" and self._table.item(row, 6) else "",
                seconds=_secs(self._table, row),
            )
            macro.steps.append(step)
        return macro

    def _del_step(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def _move(self, delta: int) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        target = row + delta
        if target < 0 or target >= self._table.rowCount():
            return
        # 简化处理：交换行数据（重建）
        macro = self._collect()
        macro.steps[row], macro.steps[target] = macro.steps[target], macro.steps[row]
        self._table.setRowCount(0)
        for step in macro.steps:
            self._append_row(step)
        self._table.setCurrentCell(target, 0)

    # ------------------------------------------------------------- files
    def _refresh_profiles(self) -> None:
        self._profiles.clear()
        for name in Macro.list_macros():
            self._profiles.addItem(name, name)

    def _load(self) -> None:
        macro = Macro.load(self._profiles.currentData() or "")
        if macro is None:
            QMessageBox.warning(self, tr("msg_error"), tr("err_macro_not_found"))
            return
        self._macro_name.setText(macro.name)
        self._loops.setValue(macro.loop_count)
        self._table.setRowCount(0)
        for step in macro.steps:
            self._append_row(step)

    def _save(self) -> None:
        macro = self._collect()
        path = macro.save()
        QMessageBox.information(self, tr("msg_macro_saved_title"),
                                tr("msg_macro_saved", path=str(path)))

    def _export(self) -> None:
        macro = self._collect()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("btn_export_macro"), f"{macro.name}.json", "JSON (*.json)")
        if not path:
            return
        Path(path).write_text(
            json.dumps(macro.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
        QMessageBox.information(self, tr("msg_macro_saved_title"),
                                tr("msg_macro_saved", path=path))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("btn_import_macro"), "", "JSON (*.json);;All (*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            macro = Macro.from_dict(data)
        except (OSError, ValueError):
            QMessageBox.warning(self, tr("msg_error"), tr("err_import_invalid"))
            return
        self._macro_name.setText(macro.name)
        self._loops.setValue(macro.loop_count)
        self._table.setRowCount(0)
        for step in macro.steps:
            self._append_row(step)

    # ------------------------------------------------------------- run
    def _run(self) -> None:
        if self._inst.state != "running":
            QMessageBox.warning(self, tr("msg_error"), tr("err_instance_not_running"))
            return
        macro = self._collect()
        self._cancel.clear()

        def job():
            self._service.adb.connect(self._inst.config.adb_port)
            return MacroRunner(self._service.adb, self._inst.config.adb_port).run(
                macro, self._cancel)

        def done(steps: int):
            QMessageBox.information(
                self, tr("msg_macro_done_title"),
                tr("msg_macro_done", steps=steps))

        from gui.widgets import AsyncRunner
        AsyncRunner(self, tr("msg_macro_running"), job, done).start()

    def _cancel_macro(self) -> None:
        self._cancel.set()


def _secs(table: QTableWidget, row: int) -> float:
    item = table.item(row, 7)
    try:
        return float(item.text()) if item else 0.5
    except (ValueError, AttributeError):
        return 0.5

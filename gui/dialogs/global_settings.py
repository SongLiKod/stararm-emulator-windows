"""全局设置对话框：主题、语言（实时生效）、全局资源阈值、外部组件路径、共享文件夹。"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from config.settings import GlobalSettings
from gui.i18n import bind, tr
from mirror.image_manager import load_sources


class _PathPicker(QWidget):
    """路径选择控件（文件 / 目录）。"""

    def __init__(self, mode: str = "file", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._btn = QPushButton()
        bind(self._btn, "btn_browse")
        self._mode = mode
        self._btn.clicked.connect(self._pick)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._btn)

    def _pick(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        if self._mode == "dir":
            path = QFileDialog.getExistingDirectory(self, tr("msg_select_dir"))
            if path:
                self._edit.setText(path)
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("msg_select_file"))
            if path:
                self._edit.setText(path)

    def text(self) -> str:
        return self._edit.text().strip()

    def setText(self, value: str) -> None:  # noqa: N802
        self._edit.setText(value)


class GlobalSettingsDialog(QDialog):
    """全局设置：外观（主题 / 语言，保存后实时生效，无需重启）。"""

    def __init__(self, service, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._settings = service.settings
        s: GlobalSettings = self._settings.get()

        self.setWindowTitle(tr("dlg_global_settings"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # 外观
        group_look = QGroupBox()
        bind(group_look, "grp_appearance")
        form_look = QFormLayout(group_look)

        self._theme = QComboBox()
        for mode, key in (("system", "theme_system"), ("light", "theme_light"),
                          ("dark", "theme_dark")):
            self._theme.addItem(tr(key), mode)
        self._theme.setCurrentIndex(self._find_data(self._theme, s.theme_mode))
        theme_label = QLabel(); bind(theme_label, "lbl_theme")
        form_look.addRow(theme_label, self._theme)

        self._language = QComboBox()
        for code, key in (("system", "lang_system"), ("zh_CN", "lang_zh"),
                           ("en_US", "lang_en")):
            self._language.addItem(tr(key), code)
        self._language.setCurrentIndex(self._find_data(self._language, s.language))
        lang_label = QLabel(); bind(lang_label, "lbl_language")
        form_look.addRow(lang_label, self._language)
        root.addWidget(group_look)

        # 资源超限保护
        group_res = QGroupBox()
        bind(group_res, "grp_resource_guard")
        form_res = QFormLayout(group_res)
        self._max_instances = QSpinBox()
        self._max_instances.setRange(1, 64)
        self._max_instances.setValue(s.max_instances)
        mi_label = QLabel(); bind(mi_label, "lbl_max_instances")
        form_res.addRow(mi_label, self._max_instances)

        self._max_cpu = QSpinBox()
        self._max_cpu.setRange(0, 256)
        self._max_cpu.setValue(s.max_total_cpu_cores)
        self._max_cpu.setSpecialValueText("Auto")
        mc_label = QLabel(); bind(mc_label, "lbl_max_cpu")
        form_res.addRow(mc_label, self._max_cpu)

        self._max_mem = QDoubleSpinBox()
        self._max_mem.setRange(0, 1024)
        self._max_mem.setDecimals(1)
        self._max_mem.setValue(float(s.max_total_memory_gb))
        self._max_mem.setSpecialValueText("Auto")
        mm_label = QLabel(); bind(mm_label, "lbl_max_mem")
        form_res.addRow(mm_label, self._max_mem)
        root.addWidget(group_res)

        # 路径
        group_path = QGroupBox()
        bind(group_path, "grp_paths")
        form_path = QFormLayout(group_path)
        self._qemu_path = _PathPicker("file")
        self._qemu_path.setText(s.qemu_path)
        qemu_label = QLabel(); bind(qemu_label, "lbl_qemu_path")
        form_path.addRow(qemu_label, self._qemu_path)

        self._adb_path = _PathPicker("file")
        self._adb_path.setText(s.adb_path)
        adb_label = QLabel(); bind(adb_label, "lbl_adb_path")
        form_path.addRow(adb_label, self._adb_path)

        src_label = QLabel(); bind(src_label, "lbl_image_source")
        self._source_combo = QComboBox()
        self._source_combo.addItem(tr("src_auto"), "auto")
        self._sources = load_sources()
        for src in self._sources:
            region = tr("src_region_china") if src["region"] == "china" else tr("src_region_global")
            self._source_combo.addItem(f"{region} · {src['name']}", src["id"])
        self._source_combo.addItem(tr("src_custom"), "custom")
        chosen = (s.image_source_id or "auto").strip() or "auto"
        index = self._find_data(self._source_combo, chosen)
        if self._source_combo.itemData(index) != chosen:
            index = 0
        self._source_combo.setCurrentIndex(index)
        self._source_combo.currentIndexChanged.connect(self._sync_source_rows)
        form_path.addRow(src_label, self._source_combo)

        self._image_source = QLineEdit(s.image_source)
        self._image_source.setPlaceholderText(tr("hint_image_source_url"))
        form_path.addRow("", self._image_source)

        check_row = QHBoxLayout()
        self._check_btn = QPushButton(); bind(self._check_btn, "btn_check_source")
        self._check_btn.clicked.connect(self._check_source)
        self._check_status = QLabel()
        self._check_status.setObjectName("secondary")
        self._check_status.setWordWrap(True)
        check_row.addWidget(self._check_btn)
        check_row.addWidget(self._check_status, 1)
        form_path.addRow("", check_row)

        src_hint = QLabel(); bind(src_hint, "hint_image_source")
        src_hint.setWordWrap(True)
        src_hint.setObjectName("secondary")
        form_path.addRow("", src_hint)
        self._sync_source_rows()

        self._shared_folder = _PathPicker("dir")
        self._shared_folder.setText(s.shared_folder)
        shared_label = QLabel(); bind(shared_label, "lbl_shared_folder")
        form_path.addRow(shared_label, self._shared_folder)
        root.addWidget(group_path)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _find_data(combo: QComboBox, data) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == data:
                return index
        return 0

    def _sync_source_rows(self) -> None:
        self._image_source.setVisible(self._source_combo.currentData() == "custom")

    def _source_base(self) -> str:
        source_id = self._source_combo.currentData()
        if source_id == "custom":
            return self._image_source.text().strip()
        for src in self._sources:
            if src["id"] == source_id:
                return src["base_url"]
        return ""

    def _check_source(self) -> None:
        """异步 HEAD 探测当前镜像源：可用 / 源可达但暂无镜像 / 无法连接。"""
        from gui.widgets import AsyncRunner
        from mirror.image_manager import ImageManager, load_sources
        base = self._source_base()
        if not base:
            self._check_status.setText(tr("err_no_image_source"))
            return
        if self._source_combo.currentData() != "custom" and not self._sources:
            self._sources = load_sources()

        def job():
            return ImageManager(self._settings).check_source(base)

        def done(result):
            state, detail = result
            if state == "ok":
                text = tr("msg_source_ok", image=detail)
            elif state == "missing":
                text = tr("msg_source_missing")
            else:
                text = tr("msg_source_unreachable", detail=detail)
            self._check_status.setText(text)

        self._check_status.setText(tr("msg_working"))
        AsyncRunner(self, tr("msg_working"), job, done).start()

    def accept(self) -> None:  # noqa: D102
        self._settings.update(
            theme_mode=self._theme.currentData(),
            language=self._language.currentData(),
            max_instances=self._max_instances.value(),
            max_total_cpu_cores=self._max_cpu.value(),
            max_total_memory_gb=int(self._max_mem.value() * 10) // 10
            if self._max_mem.value() else 0,
            qemu_path=self._qemu_path.text(),
            adb_path=self._adb_path.text(),
            image_source=self._image_source.text().strip(),
            image_source_id=str(self._source_combo.currentData() or "auto"),
            shared_folder=self._shared_folder.text(),
        )
        super().accept()

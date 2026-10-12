"""新建 ARM64 实例对话框：镜像、CPU/内存/磁盘独立配置、分辨率/DPI、网络模式、图形加速。"""
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from config.constants import (
    DEFAULT_DPI, DEFAULT_RESOLUTION, DPI_MAX, DPI_MIN, RESOLUTION_PRESETS,
)
from core.instance import InstanceConfig
from gui.i18n import bind, tr


class CreateInstanceDialog(QDialog):
    """新建实例：独立资源配置（CPU / 内存 / 磁盘）、240P-4K 分辨率、DPI、NAT/桥接。"""

    def __init__(self, service, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self.created_instance = None

        self.setWindowTitle(tr("dlg_create_instance"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # 基本信息
        group_basic = QGroupBox()
        bind(group_basic, "grp_basic")
        form_basic = QFormLayout(group_basic)
        self._name = QLineEdit()
        name_label = QLabel(); bind(name_label, "lbl_instance_name")
        form_basic.addRow(name_label, self._name)

        combo_layout = QHBoxLayout()
        self._image = QComboBox()
        self._import_btn = QPushButton()
        bind(self._import_btn, "btn_import_image")
        self._import_btn.clicked.connect(self._import_image)
        combo_layout.addWidget(self._image, 1)
        combo_layout.addWidget(self._import_btn)
        image_label = QLabel(); bind(image_label, "lbl_image")
        form_basic.addRow(image_label, combo_layout)

        self._download_btn = QPushButton()
        bind(self._download_btn, "btn_download_image")
        self._download_btn.clicked.connect(self._download_image)
        dl_hint = QLabel()
        bind(dl_hint, "hint_image_source")
        dl_hint.setWordWrap(True)
        dl_hint.setObjectName("secondary")
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._download_btn)
        btn_row.addStretch(1)
        dl_widget = QWidget()
        dl_layout = QVBoxLayout(dl_widget)
        dl_layout.setContentsMargins(0, 0, 0, 0)
        dl_layout.setSpacing(4)
        dl_layout.addLayout(btn_row)
        dl_layout.addWidget(dl_hint)
        dl_label = QLabel(); bind(dl_label, "lbl_builtin_images")
        form_basic.addRow(dl_label, dl_widget)
        root.addWidget(group_basic)

        # 资源配置
        group_res = QGroupBox()
        bind(group_res, "grp_resource")
        form_res = QFormLayout(group_res)
        self._cpu = QSpinBox(); self._cpu.setRange(1, 32); self._cpu.setValue(4)
        cpu_label = QLabel(); bind(cpu_label, "lbl_cpu")
        form_res.addRow(cpu_label, self._cpu)

        self._mem = QSpinBox(); self._mem.setRange(1, 64); self._mem.setValue(4)
        self._mem.setSuffix(" GB")
        mem_label = QLabel(); bind(mem_label, "lbl_memory")
        form_res.addRow(mem_label, self._mem)

        self._disk = QSpinBox(); self._disk.setRange(8, 512); self._disk.setValue(32)
        self._disk.setSuffix(" GB")
        disk_label = QLabel(); bind(disk_label, "lbl_disk")
        form_res.addRow(disk_label, self._disk)
        root.addWidget(group_res)

        # 显示
        group_disp = QGroupBox()
        bind(group_disp, "grp_display")
        form_disp = QFormLayout(group_disp)
        res_row = QHBoxLayout()
        self._resolution = QComboBox()
        self._resolution.addItem(tr("lbl_resolution_custom"), "")
        for label, value in RESOLUTION_PRESETS.items():
            self._resolution.addItem(f"{label} ({value})", value)
        self._resolution.setCurrentIndex(1)  # 默认 720P
        self._custom_w = QSpinBox(); self._custom_w.setRange(240, 4096); self._custom_w.setValue(1280)
        self._custom_h = QSpinBox(); self._custom_h.setRange(240, 4096); self._custom_h.setValue(720)
        res_row.addWidget(self._resolution, 1)
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._custom_w)
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._custom_h)
        res_label = QLabel(); bind(res_label, "lbl_resolution")
        form_disp.addRow(res_label, res_row)

        self._dpi = QSpinBox()
        self._dpi.setRange(DPI_MIN, DPI_MAX)
        self._dpi.setValue(DEFAULT_DPI)
        dpi_label = QLabel(); bind(dpi_label, "lbl_dpi")
        form_disp.addRow(dpi_label, self._dpi)

        self._graphics = QComboBox()
        for mode, key in (("virgl-vulkan", "graphics_vulkan"),
                          ("virgl", "graphics_gles"),
                          ("software", "graphics_software")):
            self._graphics.addItem(tr(key), mode)
        graphics_label = QLabel(); bind(graphics_label, "lbl_graphics")
        form_disp.addRow(graphics_label, self._graphics)
        root.addWidget(group_disp)

        # 网络
        group_net = QGroupBox()
        bind(group_net, "grp_network")
        form_net = QFormLayout(group_net)
        self._net_nat = QCheckBox(); bind(self._net_nat, "net_nat")
        self._net_nat.setChecked(True)
        self._net_bridge = QCheckBox(); bind(self._net_bridge, "net_bridge")
        self._net_nat.toggled.connect(lambda on: self._net_bridge.setChecked(not on))
        self._net_bridge.toggled.connect(lambda on: self._net_nat.setChecked(not on))
        net_row = QHBoxLayout()
        net_row.addWidget(self._net_nat)
        net_row.addWidget(self._net_bridge)
        net_row.addStretch(1)
        mode_label = QLabel(); bind(mode_label, "lbl_net_mode")
        form_net.addRow(mode_label, net_row)

        self._bridge_adapter = QLineEdit()
        self._bridge_adapter.setPlaceholderText(tr("hint_tap_adapter"))
        adapter_label = QLabel(); bind(adapter_label, "lbl_tap_adapter")
        form_net.addRow(adapter_label, self._bridge_adapter)
        root.addWidget(group_net)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_create"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self._on_create)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_images()

    # ------------------------------------------------------------- images
    def _load_images(self) -> None:
        self._image.clear()
        for img in self._service.images.list_images():
            suffix = "" if img.is_ready else f" [{tr('msg_image_missing')}]"
            self._image.addItem(f"{img.name}{suffix}", img.id)
        if self._image.count() == 0:
            self._image.addItem(tr("msg_no_image"), "")

    def _import_image(self) -> None:
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(self, tr("dlg_import_image"), "",
                                              "Image (image.json *.zip);;All (*)")
        if not path:
            return
        p = Path(path)
        if p.is_dir():
            src = p
        elif p.suffix.lower() == ".zip":
            src = p
        else:
            src = p.parent
        from mirror.image_manager import ImageManagerError
        try:
            self._service.images.import_image(src)
            self._load_images()
        except ImageManagerError as exc:
            QMessageBox.warning(self, tr("msg_error"), tr(exc.key))

    def _download_image(self) -> None:
        """从镜像源下载所选内置镜像（Android 11-15）；未配置镜像源时引导去设置。"""
        from PySide6.QtWidgets import QMessageBox
        from gui.widgets import AsyncRunner
        image_id = self._image.currentData()
        if not image_id:
            QMessageBox.warning(self, tr("msg_error"), tr("err_image_required"))
            return
        setting = self._service.settings.get()
        chosen = (getattr(setting, "image_source_id", "") or "auto").strip() or "auto"
        if chosen == "custom" and not (setting.image_source or "").strip():
            self._prompt_image_source()
            return

        def job():
            return self._service.images.download_builtin(image_id)

        AsyncRunner(self, tr("msg_downloading"), job,
                    lambda _img: self._load_images(),
                    lambda detail: self._show_error(detail)).start()

    def _prompt_image_source(self) -> None:
        """未配置镜像源：给出可读提示并提供“打开全局设置”入口（设置后继续下载）。"""
        from PySide6.QtWidgets import QMessageBox
        from gui.dialogs.global_settings import GlobalSettingsDialog
        box = QMessageBox(QMessageBox.Icon.Information, tr("lbl_image_source"),
                          tr("err_no_image_source"),
                          QMessageBox.StandardButton.NoButton, self)
        settings_btn = box.addButton(tr("btn_open_settings"),
                                     QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("btn_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(settings_btn)
        box.exec()
        if box.clickedButton() is settings_btn and \
                GlobalSettingsDialog(self._service, self).exec():
            self._download_image()

    def _show_error(self, detail: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, tr("msg_error"), detail[:400])

    # ------------------------------------------------------------- create
    def _on_create(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        name = self._name.text().strip()
        image_id = self._image.currentData()
        if not name:
            QMessageBox.warning(self, tr("msg_error"), tr("err_name_required"))
            return
        if not image_id:
            QMessageBox.warning(self, tr("msg_error"), tr("err_image_required"))
            return
        network_mode = "nat" if self._net_nat.isChecked() else "bridge"
        if network_mode == "bridge" and not self._bridge_adapter.text().strip():
            QMessageBox.warning(self, tr("msg_error"), tr("err_tap_required"))
            return
        resolution = self._resolution.currentData() or \
            f"{self._custom_w.value()}x{self._custom_h.value()}"
        config = InstanceConfig(
            cpu_cores=self._cpu.value(),
            memory_mb=self._mem.value() * 1024,
            disk_gb=self._disk.value(),
            resolution=resolution or DEFAULT_RESOLUTION,
            dpi=self._dpi.value(),
            network_mode=network_mode,
            bridge_adapter=self._bridge_adapter.text().strip(),
            graphics=self._graphics.currentData() or "virgl-vulkan",
        )
        try:
            self.created_instance = self._service.instances.create(name, image_id, config)
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("msg_error"), tr(str(exc.args[0] if exc.args else "err_unknown")))
            return
        self.accept()

"""单实例设置对话框：性能 / 显示 / 网络 / 设备伪装 / 位置与电源 / ADB。

保存后：磁盘/CPU 等需重启生效；分辨率/DPI、设备伪装、GPS、电池在运行中实时应用。
"""
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from config.constants import DEFAULT_DPI, DPI_MAX, DPI_MIN, RESOLUTION_PRESETS
from core.guest_agent import GuestAgentClient
from gui.i18n import bind, tr
from tools import device_profile as profile_tool


class InstanceSettingsDialog(QDialog):
    def __init__(self, service, instance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._inst = instance
        cfg = instance.config

        self.setWindowTitle(tr("dlg_instance_settings", name=instance.name))
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        self._tabs = QTabWidget()

        # -------------------------------------------------- 性能
        page_res = QWidget()
        form_res = QFormLayout(page_res)
        self._cpu = QSpinBox(); self._cpu.setRange(1, 32); self._cpu.setValue(cfg.cpu_cores)
        cpu_label = QLabel(); bind(cpu_label, "lbl_cpu")
        form_res.addRow(cpu_label, self._cpu)
        self._mem = QSpinBox(); self._mem.setRange(1, 64); self._mem.setValue(cfg.memory_mb // 1024)
        self._mem.setSuffix(" GB")
        mem_label = QLabel(); bind(mem_label, "lbl_memory")
        form_res.addRow(mem_label, self._mem)
        self._disk = QSpinBox(); self._disk.setRange(8, 512); self._disk.setValue(cfg.disk_gb)
        self._disk.setSuffix(" GB")
        disk_note = QLabel(); bind(disk_note, "lbl_disk_note")
        self._disk.setReadOnly(True)  # 磁盘容量创建时确定（覆盖层）
        disk_label = QLabel(); bind(disk_label, "lbl_disk")
        form_res.addRow(disk_label, self._disk)
        form_res.addRow(disk_note, QLabel())
        tab_res = QLabel(); bind(tab_res, "tab_perf")
        self._tabs.addTab(page_res, tr("tab_perf"))

        # -------------------------------------------------- 显示
        page_disp = QWidget()
        form_disp = QFormLayout(page_disp)
        res_row = QHBoxLayout()
        self._resolution = QComboBox()
        self._resolution.addItem(tr("lbl_resolution_custom"), "")
        for label, value in RESOLUTION_PRESETS.items():
            self._resolution.addItem(f"{label} ({value})", value)
        # 匹配当前分辨率
        current = cfg.resolution
        index = self._resolution.findData(current)
        if index < 0:
            try:
                w, h = current.lower().split("x", 1)
                self._custom_w = QSpinBox(); self._custom_w.setRange(240, 4096); self._custom_w.setValue(int(w))
                self._custom_h = QSpinBox(); self._custom_h.setRange(240, 4096); self._custom_h.setValue(int(h))
            except ValueError:
                self._custom_w = QSpinBox(); self._custom_w.setRange(240, 4096); self._custom_w.setValue(1280)
                self._custom_h = QSpinBox(); self._custom_h.setRange(240, 4096); self._custom_h.setValue(720)
        else:
            self._custom_w = QSpinBox(); self._custom_w.setRange(240, 4096); self._custom_w.setValue(1280)
            self._custom_h = QSpinBox(); self._custom_h.setRange(240, 4096); self._custom_h.setValue(720)
            self._resolution.setCurrentIndex(index)
        res_row.addWidget(self._resolution, 1)
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._custom_w)
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._custom_h)
        res_label = QLabel(); bind(res_label, "lbl_resolution")
        form_disp.addRow(res_label, res_row)
        self._dpi = QSpinBox()
        self._dpi.setRange(DPI_MIN, DPI_MAX); self._dpi.setValue(cfg.dpi or DEFAULT_DPI)
        dpi_label = QLabel(); bind(dpi_label, "lbl_dpi")
        form_disp.addRow(dpi_label, self._dpi)
        self._fullscreen = QCheckBox(); bind(self._fullscreen, "lbl_fullscreen")
        self._fullscreen.setChecked(cfg.fullscreen)
        form_disp.addRow(self._fullscreen)
        self._graphics = QComboBox()
        for mode, key in (("virgl-vulkan", "graphics_vulkan"),
                          ("virgl", "graphics_gles"),
                          ("software", "graphics_software")):
            self._graphics.addItem(tr(key), mode)
        idx = self._graphics.findData(cfg.graphics)
        self._graphics.setCurrentIndex(idx if idx >= 0 else 0)
        graphics_label = QLabel(); bind(graphics_label, "lbl_graphics")
        form_disp.addRow(graphics_label, self._graphics)
        self._tabs.addTab(page_disp, tr("tab_display"))

        # -------------------------------------------------- 网络
        page_net = QWidget()
        form_net = QFormLayout(page_net)
        self._net_nat = QCheckBox(); bind(self._net_nat, "net_nat")
        self._net_nat.setChecked(cfg.network_mode == "nat")
        self._net_bridge = QCheckBox(); bind(self._net_bridge, "net_bridge")
        self._net_bridge.setChecked(cfg.network_mode == "bridge")
        self._net_nat.toggled.connect(lambda on: self._net_bridge.setChecked(not on))
        self._net_bridge.toggled.connect(lambda on: self._net_nat.setChecked(not on))
        net_row = QHBoxLayout()
        net_row.addWidget(self._net_nat)
        net_row.addWidget(self._net_bridge)
        net_row.addStretch(1)
        mode_label = QLabel(); bind(mode_label, "lbl_net_mode")
        form_net.addRow(mode_label, net_row)
        self._bridge_adapter = QLineEdit(cfg.bridge_adapter)
        adapter_label = QLabel(); bind(adapter_label, "lbl_tap_adapter")
        form_net.addRow(adapter_label, self._bridge_adapter)
        self._tabs.addTab(page_net, tr("tab_network"))

        # -------------------------------------------------- 设备伪装
        page_dev = QWidget()
        form_dev = QFormLayout(page_dev)
        self._brand = QComboBox()
        self._brand.setEditable(True)
        for brand in profile_tool.COMMON_BRANDS:
            self._brand.addItem(brand)
        self._brand.setCurrentText(cfg.device.brand)
        brand_label = QLabel(); bind(brand_label, "lbl_brand")
        form_dev.addRow(brand_label, self._brand)
        self._model = QLineEdit(cfg.device.model)
        model_label = QLabel(); bind(model_label, "lbl_model")
        form_dev.addRow(model_label, self._model)
        self._serial = QLineEdit(cfg.device.serial)
        serial_label = QLabel(); bind(serial_label, "lbl_serialno")
        form_dev.addRow(serial_label, self._serial)
        self._imei = QLineEdit(cfg.device.imei)
        imei_label = QLabel(); bind(imei_label, "lbl_imei")
        form_dev.addRow(imei_label, self._imei)
        self._android_id = QLineEdit(cfg.device.android_id)
        aid_label = QLabel(); bind(aid_label, "lbl_android_id")
        form_dev.addRow(aid_label, self._android_id)
        self._fingerprint = QLineEdit(cfg.device.fingerprint)
        fp_label = QLabel(); bind(fp_label, "lbl_fingerprint")
        form_dev.addRow(fp_label, self._fingerprint)
        gen_row = QHBoxLayout()
        self._gen_btn = QPushButton()
        bind(self._gen_btn, "btn_generate_profile")
        self._gen_btn.clicked.connect(self._generate)
        gen_row.addWidget(self._gen_btn)
        gen_row.addStretch(1)
        form_dev.addRow(gen_row)
        self._tabs.addTab(page_dev, tr("tab_device"))

        # -------------------------------------------------- 位置与电源
        page_loc = QWidget()
        form_loc = QFormLayout(page_loc)
        self._lat = QDoubleSpinBox()
        self._lat.setRange(-90, 90); self._lat.setDecimals(6); self._lat.setValue(cfg.gps.latitude)
        lat_label = QLabel(); bind(lat_label, "lbl_latitude")
        form_loc.addRow(lat_label, self._lat)
        self._lng = QDoubleSpinBox()
        self._lng.setRange(-180, 180); self._lng.setDecimals(6); self._lng.setValue(cfg.gps.longitude)
        lng_label = QLabel(); bind(lng_label, "lbl_longitude")
        form_loc.addRow(lng_label, self._lng)
        self._battery = QSpinBox()
        self._battery.setRange(0, 100); self._battery.setValue(cfg.battery.level)
        bat_label = QLabel(); bind(bat_label, "lbl_battery_level")
        form_loc.addRow(bat_label, self._battery)
        self._charging = QCheckBox(); bind(self._charging, "lbl_charging")
        self._charging.setChecked(cfg.battery.charging)
        form_loc.addRow(self._charging)
        self._tabs.addTab(page_loc, tr("tab_geo"))

        # -------------------------------------------------- ADB
        page_adb = QWidget()
        form_adb = QFormLayout(page_adb)
        adb_text = QLineEdit(f"adb connect 127.0.0.1:{cfg.adb_port}")
        adb_text.setReadOnly(True)
        adb_label = QLabel(); bind(adb_label, "lbl_adb_port")
        form_adb.addRow(adb_label, adb_text)
        agent_text = QLineEdit(f"127.0.0.1:{cfg.agent_port} ({tr('lbl_agent_port')})")
        agent_text.setReadOnly(True)
        form_adb.addRow(agent_text)
        self._tabs.addTab(page_adb, tr("tab_adb"))

        root.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_save"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------- actions
    def _generate(self) -> None:
        profile = profile_tool.generate_profile()
        self._brand.setCurrentText(profile.brand)
        self._model.setText(profile.model)
        self._serial.setText(profile.serial)
        self._imei.setText(profile.imei)
        self._android_id.setText(profile.android_id)
        self._fingerprint.setText(profile.fingerprint)

    def _collect(self) -> dict:
        resolution = self._resolution.currentData() or \
            f"{self._custom_w.value()}x{self._custom_h.value()}"
        return {
            "cpu_cores": self._cpu.value(),
            "memory_mb": self._mem.value() * 1024,
            "resolution": resolution,
            "dpi": self._dpi.value(),
            "fullscreen": self._fullscreen.isChecked(),
            "graphics": self._graphics.currentData() or "virgl-vulkan",
            "network_mode": "nat" if self._net_nat.isChecked() else "bridge",
            "bridge_adapter": self._bridge_adapter.text().strip(),
            "device.brand": self._brand.currentText().strip(),
            "device.manufacturer": self._brand.currentText().strip(),
            "device.model": self._model.text().strip(),
            "device.serial": self._serial.text().strip(),
            "device.imei": self._imei.text().strip(),
            "device.android_id": self._android_id.text().strip(),
            "device.fingerprint": self._fingerprint.text().strip(),
            "gps.latitude": self._lat.value(),
            "gps.longitude": self._lng.value(),
            "battery.level": self._battery.value(),
            "battery.charging": self._charging.isChecked(),
        }

    def _on_save(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from gui.widgets import AsyncRunner
        fields = self._collect()
        if fields["network_mode"] == "bridge" and not fields["bridge_adapter"]:
            QMessageBox.warning(self, tr("msg_error"), tr("err_tap_required"))
            return
        self._inst = self._service.instances.update_config(self._inst.id, **fields)
        if self._inst.state == "running":
            def job():
                agent = GuestAgentClient(port=self._inst.config.agent_port)
                image = self._service.images.get(self._inst.image_id)
                version = image.android_version if image else 13
                cfg = self._inst.config
                self._service.adb.adb_root(cfg.adb_port)
                report = profile_tool.apply_profile(self._service.adb, agent, cfg, version)
                w, h = cfg.resolution.lower().split("x", 1)
                self._service.adb.wm_size(cfg.adb_port, int(w), int(h))
                self._service.adb.wm_density(cfg.adb_port, cfg.dpi)
                return sum(1 for _, ok in report if ok)

            def done(_ok: int):
                QMessageBox.information(self, tr("msg_settings_saved"),
                                        tr("msg_settings_saved"))

            AsyncRunner(self, tr("msg_applying"), job, done).start()
        self.accept()

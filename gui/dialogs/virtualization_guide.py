"""虚拟化开启中文教程对话框：BIOS 步骤 + 主板厂商按键表 + Windows 虚拟化平台。

按检测结论（core.virtualization reason）分节渲染，避免"已开启却提示未开启"：
- firmware：BIOS 未开启 → 高亮 BIOS 步骤
- whpx    ：BIOS 已开启、仅 Windows「虚拟机监控程序平台」功能缺失 → 高亮该步骤，
            并提供一键启用（请求 UAC 管理员权限）
- ok      ：硬件加速已就绪
"""
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTextBrowser, QVBoxLayout, QWidget,
)

from core.virtualization import (
    REASON_FIRMWARE, REASON_OK, REASON_WHPX, VirtualizationStatus,
)
from gui.i18n import bind, tr

VENDORS = [
    ("Dell", "F2 / Del"),
    ("HP", "Esc / F10"),
    ("Lenovo 联想", "F1 / F2"),
    ("ASUS 华硕", "Del / F2"),
    ("MSI 微星", "Del"),
    ("Gigabyte 技嘉", "Del"),
    ("ASRock 华擎", "Del / F2"),
    ("Intel NUC", "F2"),
]

HIGHLIGHT = "#FF7D00"   # 需要用户处理的章节
MUTED = "#86909C"       # 已就绪 / 暂不需要处理的章节


def _section(title_key: str, highlight: bool, items: list) -> str:
    color = HIGHLIGHT if highlight else MUTED
    rows = "".join(f"<li>{tr(key)}</li>" for key in items)
    return f'<h3 style="color:{color};">{tr(title_key)}</h3><ol>{rows}</ol>'


def guide_html(status: Optional[VirtualizationStatus] = None) -> str:
    """教程内容（双语词条拼装，按检测结论高亮待处理章节）。"""
    reason = status.reason if status else REASON_FIRMWARE
    bios_ok = status is not None and (reason == REASON_OK or status.needs_whpx)
    vendor_rows = "".join(
        f"<tr><td>{name}</td><td>{key}</td></tr>" for name, key in VENDORS)

    blocks = [f"""
    <h2 style="color:#1677FF;">{tr('vt_guide_title')}</h2>
    <p>{tr('vt_guide_intro')}</p>
    """]

    if bios_ok:
        blocks.append(
            f'<p style="color:#36CFC9;">{tr("vt_guide_bios_ok")}</p>')

    blocks.append(_section("vt_guide_bios_title", reason == REASON_FIRMWARE,
                           ["vt_guide_step1", "vt_guide_step2", "vt_guide_step3",
                            "vt_guide_step4", "vt_guide_step5"]))

    if reason == REASON_FIRMWARE:
        blocks.append(f"""
        <h3 style="color:{MUTED};">{tr('vt_guide_vendor_title')}</h3>
        <table border="1" cellspacing="0" cellpadding="4" width="80%"
               style="border-color:#E5E6EB;">
            <tr><th>{tr('vt_guide_vendor')}</th><th>{tr('vt_guide_key')}</th></tr>
            {vendor_rows}
        </table>
        """)

    blocks.append(_section("vt_guide_whpx_title", reason == REASON_WHPX,
                           ["vt_guide_whpx_1", "vt_guide_whpx_2", "vt_guide_whpx_3"]))
    blocks.append(f'<p style="color:#36CFC9;">{tr("vt_guide_done")}</p>')
    return "".join(blocks)


class VirtualizationGuideDialog(QDialog):
    def __init__(self, service, parent: Optional[QWidget] = None,
                 on_recheck=None) -> None:
        super().__init__(parent)
        self._service = service
        self._on_recheck = on_recheck
        self.setWindowTitle(tr("vt_guide_window_title"))
        self.setMinimumSize(660, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        layout.addWidget(self._browser)

        self._enable_btn = QPushButton()
        self._enable_btn.setObjectName("primary")
        bind(self._enable_btn, "btn_enable_whpx")
        self._enable_btn.clicked.connect(self._enable_whpx)
        self._enable_btn.hide()
        layout.addWidget(self._enable_btn)

        row = QHBoxLayout()
        self._recheck_btn = QPushButton()
        bind(self._recheck_btn, "btn_recheck")
        self._recheck_btn.clicked.connect(self._recheck)
        self._status_label = QLabel()
        self._status_label.setObjectName("secondary")
        row.addWidget(self._status_label, 1)
        row.addWidget(self._recheck_btn)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("btn_close"))
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _b: self.reject())
        layout.addWidget(buttons)

        self._status: Optional[VirtualizationStatus] = None
        self._render()

    # ------------------------------------------------------------- render
    def _current_status(self) -> VirtualizationStatus:
        return self._service.qemu.virtualization()

    def _render(self) -> None:
        self._status = self._current_status()
        self._browser.setHtml(guide_html(self._status))
        status = self._status
        if status.reason == REASON_OK:
            self._status_label.setText(tr("vt_status_enabled"))
        elif status.reason == REASON_FIRMWARE:
            self._status_label.setText(tr("vt_status_disabled"))
        elif status.reason == REASON_WHPX:
            self._status_label.setText(tr("vt_status_whpx_missing"))
        else:
            self._status_label.setText(tr("vt_status_unknown"))
        self._enable_btn.setVisible(status.reason == REASON_WHPX)

    # ------------------------------------------------------------- actions
    def _recheck(self) -> None:
        self._service.qemu.virtualization(refresh=True)
        self._render()
        if self._on_recheck is not None:
            self._on_recheck()

    def _enable_whpx(self) -> None:
        """一键启用 Windows「虚拟机监控程序平台」（需要 UAC 管理员授权）。"""
        import ctypes
        params = ('-NoProfile -Command "Enable-WindowsOptionalFeature -Online '
                  '-FeatureName HypervisorPlatform -All -NoRestart"')
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe", params, None, 1)
        except Exception:
            rc = 0
        if rc <= 32:
            QMessageBox.warning(self, tr("msg_error"), tr("msg_whpx_enable_failed"))
            return
        QMessageBox.information(self, tr("msg_tip"), tr("msg_whpx_enable_started"))

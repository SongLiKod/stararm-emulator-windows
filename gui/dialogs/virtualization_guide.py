"""虚拟化开启中文教程对话框：BIOS 步骤 + 主板厂商按键表 + Windows 虚拟化平台。

对应需求：自动检测主机 VT-x/AMD-V 状态，未开启时弹出中文教程引导（降低使用门槛）。
"""
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QVBoxLayout, QWidget,
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


def guide_html() -> str:
    """教程内容（双语词条拼装，主题通用主色强调）。"""
    vendor_rows = "".join(
        f"<tr><td>{name}</td><td>{key}</td></tr>" for name, key in VENDORS)
    return f"""
    <h2 style="color:#1677FF;">{tr('vt_guide_title')}</h2>
    <p>{tr('vt_guide_intro')}</p>
    <h3 style="color:#FF7D00;">{tr('vt_guide_bios_title')}</h3>
    <ol>
        <li>{tr('vt_guide_step1')}</li>
        <li>{tr('vt_guide_step2')}</li>
        <li>{tr('vt_guide_step3')}</li>
        <li>{tr('vt_guide_step4')}</li>
        <li>{tr('vt_guide_step5')}</li>
    </ol>
    <h3 style="color:#FF7D00;">{tr('vt_guide_vendor_title')}</h3>
    <table border="1" cellspacing="0" cellpadding="4" width="80%">
        <tr><th>{tr('vt_guide_vendor')}</th><th>{tr('vt_guide_key')}</th></tr>
        {vendor_rows}
    </table>
    <h3 style="color:#FF7D00;">{tr('vt_guide_whpx_title')}</h3>
    <ol>
        <li>{tr('vt_guide_whpx_1')}</li>
        <li>{tr('vt_guide_whpx_2')}</li>
        <li>{tr('vt_guide_whpx_3')}</li>
    </ol>
    <p style="color:#36CFC9;">{tr('vt_guide_done')}</p>
    """


class VirtualizationGuideDialog(QDialog):
    def __init__(self, service, parent: Optional[QWidget] = None,
                 on_recheck=None) -> None:
        super().__init__(parent)
        self._service = service
        self._on_recheck = on_recheck
        self.setWindowTitle(tr("vt_guide_window_title"))
        self.setMinimumSize(640, 560)

        layout = QVBoxLayout(self)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        layout.addWidget(self._browser)

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

        self._render()

    def _render(self) -> None:
        self._browser.setHtml(guide_html())
        vt = self._service.qemu.virtualization()
        if vt.accelerated:
            self._status_label.setText(tr("vt_status_enabled"))
        elif vt.firmware_disabled:
            self._status_label.setText(tr("vt_status_disabled"))
        else:
            self._status_label.setText(tr("vt_status_unknown"))

    def _recheck(self) -> None:
        self._service.qemu.virtualization(refresh=True)
        self._render()
        if self._on_recheck is not None:
            self._on_recheck()

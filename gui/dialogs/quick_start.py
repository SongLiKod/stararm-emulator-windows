"""新手使用教程：三步上手（创建实例 -> 启动 -> 安装 APK）+ 进阶能力说明。

对应反馈：新用户不清楚"这是安卓模拟器吗 / 怎么装 APK"，提供随时可打开的图文教程。
"""
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget,
)

from gui.i18n import tr


def quick_start_html() -> str:
    """教程正文（双语词条拼装，主题通用主色强调）。"""
    return f"""
    <h2 style="color:#1677FF;">{tr('dlg_quick_start')}</h2>
    <p>{tr('qs_intro')}</p>
    <h3 style="color:#1677FF;">{tr('qs_step1_title')}</h3>
    <p>{tr('qs_step1_text')}</p>
    <h3 style="color:#1677FF;">{tr('qs_step2_title')}</h3>
    <p>{tr('qs_step2_text')}</p>
    <h3 style="color:#FF7D00;">{tr('qs_step3_title')}</h3>
    <p>{tr('qs_step3_text')}</p>
    <h3 style="color:#36CFC9;">{tr('qs_step4_title')}</h3>
    <p>{tr('qs_step4_text')}</p>
    """


class QuickStartDialog(QDialog):
    """使用教程对话框（只读图文，随时可打开）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_quick_start"))
        self.setMinimumSize(620, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setHtml(quick_start_html())
        layout.addWidget(self._browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("btn_close"))
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)

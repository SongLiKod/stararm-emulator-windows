"""主题配色资源加载与 QSS 生成（纯数据层，无 GUI 依赖）。

三套主题模式：跟随系统、浅色、深色；配色严格按产品视觉规范。
"""
import json
from typing import Dict

from config import paths

THEME_MODES = ("system", "light", "dark")

# 主题通用主色（品牌核心色，三套主题通用）
COMMON_COLORS = {
    "primary": "#1677FF",   # 科技蓝：按钮高亮、选中、进度条、重点操作
    "success": "#36CFC9",   # 青绿：运行状态、启动成功、正向反馈
    "warning": "#FF7D00",   # 橙红：报错、警告、实例异常、高危操作
}


def load_theme(mode: str) -> Dict[str, str]:
    """加载指定主题配色（light/dark）。"""
    if mode not in ("light", "dark"):
        mode = "light"
    try:
        data = json.loads((paths.resource_dir() / "themes" / f"{mode}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    merged = dict(COMMON_COLORS)
    merged.update(data)
    return merged


def load_all_themes() -> Dict[str, Dict[str, str]]:
    return {"light": load_theme("light"), "dark": load_theme("dark")}


def build_qss(p: Dict[str, str]) -> str:
    """由配色字典生成全局 QSS 样式表。"""
    return f"""
QMainWindow, QDialog {{
    background-color: {p['background']};
}}
QMenu, QMenuBar {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}
QMenu::item:selected, QMenuBar::item:selected {{
    background-color: {p['hover']};
}}
QWidget#card {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
}}
QWidget#banner {{
    background-color: {p['surface']};
    border: 1px solid {p['warning']};
    border-radius: 6px;
}}
QLabel {{
    color: {p['text']};
    background: transparent;
    border: none;
}}
QLabel#secondary {{
    color: {p['text_secondary']};
}}
QPushButton {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: {p['hover']};
    border-color: {p['primary']};
}}
QPushButton:pressed {{
    border-color: {p['primary']};
}}
QPushButton:disabled {{
    color: {p['text_secondary']};
    border-color: {p['border']};
}}
QPushButton#primary {{
    background-color: {p['primary']};
    color: #FFFFFF;
    border: 1px solid {p['primary']};
}}
QPushButton#primary:hover {{
    background-color: {p['primary']};
    border-color: {p['primary']};
    opacity: 0.9;
}}
QPushButton#primary:disabled {{
    background-color: {p['text_secondary']};
}}
QPushButton#danger {{
    background-color: {p['warning']};
    color: #FFFFFF;
    border: 1px solid {p['warning']};
}}
QPushButton#danger:hover {{
    background-color: {p['warning']};
    border-color: {p['text']};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {p['primary']};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {p['primary']};
}}
QComboBox QAbstractItemView {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    selection-background-color: {p['primary']};
    selection-color: #FFFFFF;
}}
QTableWidget {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    gridline-color: {p['border']};
    selection-background-color: {p['primary']};
    selection-color: #FFFFFF;
    alternate-background-color: {p['background']};
}}
QHeaderView::section {{
    background-color: {p['background']};
    color: {p['text']};
    border: none;
    border-bottom: 1px solid {p['border']};
    padding: 6px;
}}
QTableCornerButton::section {{
    background-color: {p['background']};
    border: none;
}}
QTabWidget::pane {{
    border: 1px solid {p['border']};
    background-color: {p['surface']};
}}
QTabBar::tab {{
    background-color: {p['background']};
    color: {p['text_secondary']};
    padding: 6px 14px;
    border: 1px solid {p['border']};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background-color: {p['surface']};
    color: {p['primary']};
    border-color: {p['primary']};
}}
QToolBar {{
    background-color: {p['surface']};
    border: none;
    border-bottom: 1px solid {p['border']};
    spacing: 4px;
    padding: 4px;
}}
QStatusBar {{
    background-color: {p['surface']};
    color: {p['text']};
    border-top: 1px solid {p['border']};
}}
QStatusBar QLabel {{
    color: {p['text_secondary']};
    padding: 0 8px;
}}
QListWidget {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}
QListWidget::item:hover {{
    background-color: {p['hover']};
}}
QListWidget::item:selected {{
    background-color: {p['primary']};
    color: #FFFFFF;
}}
QCheckBox, QRadioButton {{
    color: {p['text']};
    background: transparent;
    spacing: 6px;
}}
QGroupBox {{
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
}}
QGroupBox::title {{
    color: {p['text_secondary']};
    subcontrol-origin: margin;
    left: 10px;
}}
QToolTip {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}
QProgressBar {{
    background-color: {p['background']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    text-align: center;
    color: {p['text']};
}}
QProgressBar::chunk {{
    background-color: {p['primary']};
    border-radius: 5px;
}}
QScrollBar:vertical {{
    background-color: {p['background']};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {p['border']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {p['text_secondary']};
}}
QScrollBar:horizontal {{
    background-color: {p['background']};
    height: 10px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {p['border']};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
"""

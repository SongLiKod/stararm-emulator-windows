"""主题配色资源加载与 QSS 生成（纯数据层，无 GUI 依赖）。

三套主题模式：跟随系统、浅色、深色；配色严格按产品视觉规范（resource/themes/*.json）。
样式风格：圆角卡片、柔和描边、清晰的悬浮/按下反馈、去网格化表格、轻量滚动条。
"""
import json
from string import Template
from typing import Dict

from config import paths

THEME_MODES = ("system", "light", "dark")

# 主题通用主色（品牌核心色，三套主题通用）
COMMON_COLORS = {
    "primary": "#1677FF",   # 科技蓝：按钮高亮、选中、进度条、重点操作
    "success": "#36CFC9",   # 青绿：运行状态、启动成功、正向反馈
    "warning": "#FF7D00",   # 橙红：报错、警告、实例异常、高危操作
}

# 主题文件缺失时的兜底配色（浅色基准），保证 QSS 永不 KeyError
DEFAULT_TOKENS = {
    "background": "#F5F7FA",
    "surface": "#FFFFFF",
    "text": "#1D2129",
    "text_secondary": "#86909C",
    "border": "#E5E6EB",
    "hover": "#E8F3FF",
    "primary_hover": "#4096FF",
    "primary_pressed": "#0958D9",
    "success_text": "#0E9384",
    "warning_text": "#D46B08",
}


def load_theme(mode: str) -> Dict[str, str]:
    """加载指定主题配色（light/dark），并与品牌主色、兜底配色合并。"""
    if mode not in ("light", "dark"):
        mode = "light"
    try:
        data = json.loads((paths.resource_dir() / "themes" / f"{mode}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULT_TOKENS)
    merged.update(COMMON_COLORS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if isinstance(v, str)})
    return merged


def load_all_themes() -> Dict[str, Dict[str, str]]:
    return {"light": load_theme("light"), "dark": load_theme("dark")}


# 全局样式表（$token 由配色字典代入；纯模板，避免 f-string 大括号转义）
_QSS_TEMPLATE = Template("""
QMainWindow, QDialog {
    background-color: $background;
}

QLabel {
    color: $text;
    background: transparent;
    border: none;
}
QLabel#secondary {
    color: $text_secondary;
}
QLabel#success {
    color: $success_text;
}
QLabel#warning {
    color: $warning_text;
}
QLabel#welcome_title {
    font-size: 24px;
    font-weight: bold;
    color: $text;
}
QLabel#welcome_desc {
    font-size: 14px;
    color: $text_secondary;
}
QLabel#step_title {
    font-size: 15px;
    font-weight: bold;
    color: $text;
}
QLabel#step_index {
    background-color: $primary;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}

QWidget#card, QWidget#welcome {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QWidget#banner {
    background-color: rgba(255, 125, 0, 0.10);
    border: 1px solid $warning;
    border-radius: 10px;
}
QWidget#instance_table {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QStackedWidget {
    background: transparent;
}

QPushButton {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 16px;
    min-height: 30px;
}
QPushButton:hover {
    background-color: $hover;
    border-color: $primary;
}
QPushButton:pressed {
    background-color: $surface;
    border-color: $primary;
}
QPushButton:focus {
    border: 1px solid $primary;
}
QPushButton:disabled {
    background-color: transparent;
    color: $text_secondary;
    border: 1px solid $border;
}
QPushButton#primary {
    background-color: $primary;
    color: #FFFFFF;
    border: 1px solid $primary;
    font-weight: bold;
}
QPushButton#primary:hover {
    background-color: $primary_hover;
    border-color: $primary_hover;
}
QPushButton#primary:pressed {
    background-color: $primary_pressed;
    border-color: $primary_pressed;
}
QPushButton#primary:disabled {
    background-color: $border;
    color: $text_secondary;
    border: none;
}
QPushButton#danger {
    background-color: $warning;
    color: #FFFFFF;
    border: 1px solid $warning;
}
QPushButton#danger:hover {
    background-color: $surface;
    color: $warning;
    border: 1px solid $warning;
}
QPushButton#danger:pressed {
    background-color: $warning;
    color: #FFFFFF;
}
QPushButton#danger:disabled {
    background-color: transparent;
    color: $text_secondary;
    border: 1px solid $border;
}
QPushButton#vt_status {
    background: transparent;
    border: none;
    padding: 2px 8px;
}
QPushButton#banner_close {
    background: transparent;
    border: none;
    color: $text_secondary;
    border-radius: 13px;
    padding: 0;
    min-width: 26px;
    min-height: 26px;
    font-size: 16px;
}
QPushButton#banner_close:hover {
    background-color: rgba(255, 125, 0, 0.22);
    color: $warning;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QTextBrowser {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 30px;
    selection-background-color: $primary;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus {
    border: 1px solid $primary;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    color: $text_secondary;
    background-color: $background;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    selection-background-color: $primary;
    selection-color: #FFFFFF;
}

QMenuBar {
    background-color: transparent;
    border: none;
    padding: 2px 0;
}
QMenuBar::item {
    background: transparent;
    color: $text;
    padding: 6px 12px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background-color: $hover;
}
QMenu {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    color: $text;
    padding: 7px 28px 7px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: $hover;
    color: $text;
}
QMenu::item:disabled {
    color: $text_secondary;
}
QMenu::separator {
    height: 1px;
    background-color: $border;
    margin: 6px 10px;
}

QTableWidget, QTableView {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 12px;
    gridline-color: transparent;
    alternate-background-color: transparent;
    selection-background-color: rgba(22, 119, 255, 0.14);
    selection-color: $text;
}
QTableWidget::item, QTableView::item {
    border: none;
    padding: 0 8px;
}
QTableWidget::item:hover, QTableView::item:hover {
    background-color: rgba(22, 119, 255, 0.07);
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: rgba(22, 119, 255, 0.14);
    color: $text;
}
QHeaderView::section {
    background-color: transparent;
    color: $text_secondary;
    border: none;
    border-bottom: 1px solid $border;
    padding: 10px 8px;
    font-weight: bold;
}
QHeaderView::section:hover {
    color: $text;
}
QTableCornerButton::section {
    background-color: transparent;
    border: none;
}

QListWidget {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background-color: $hover;
}
QListWidget::item:selected {
    background-color: rgba(22, 119, 255, 0.14);
    color: $text;
}

QTabWidget::pane {
    border: 1px solid $border;
    background-color: $surface;
    border-radius: 12px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: $text_secondary;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:hover {
    color: $text;
}
QTabBar::tab:selected {
    background-color: $surface;
    color: $primary;
    border: 1px solid $border;
    border-bottom: none;
    font-weight: bold;
}
QTabWidget QPlainTextEdit, QTabWidget QTextEdit {
    border: none;
    background: transparent;
    border-radius: 0;
}

QToolBar {
    background-color: transparent;
    border: none;
    spacing: 6px;
    padding: 0 0 2px 0;
}
QToolBar::separator {
    background-color: $border;
    width: 1px;
    margin: 6px 4px;
}

QStatusBar {
    background-color: $surface;
    border-top: 1px solid $border;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    color: $text_secondary;
    padding: 0 8px;
}

QSplitter::handle {
    background: transparent;
}
QSplitter::handle:vertical {
    height: 8px;
}
QSplitter::handle:horizontal {
    width: 8px;
}

QCheckBox, QRadioButton {
    color: $text;
    background: transparent;
    spacing: 8px;
}
QCheckBox:disabled, QRadioButton:disabled {
    color: $text_secondary;
}

QGroupBox {
    color: $text;
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 18px;
    padding: 14px 12px 12px 12px;
}
QGroupBox::title {
    color: $text_secondary;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 6px;
    font-weight: bold;
}

QProgressBar {
    background-color: $background;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    text-align: center;
    min-height: 16px;
}
QProgressBar::chunk {
    background-color: $primary;
    border-radius: 7px;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background-color: $border;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background-color: $text_secondary;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background-color: $border;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background-color: $text_secondary;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
    border: none;
    background: transparent;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
QScrollBar::corner {
    background: transparent;
}

QToolTip {
    background-color: $text;
    color: $background;
    border: none;
    padding: 6px 10px;
}
""")


def build_qss(p: Dict[str, str]) -> str:
    """由配色字典生成全局 QSS 样式表（缺失配色自动用默认值兜底）。"""
    tokens = dict(DEFAULT_TOKENS)
    tokens.update(COMMON_COLORS)
    tokens.update({k: v for k, v in (p or {}).items() if isinstance(v, str)})
    return _QSS_TEMPLATE.substitute(tokens)
